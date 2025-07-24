from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import json
import pytz
import threading
import time
from datetime import datetime, timedelta

app = Flask(__name__)

# 日本のタイムゾーンを設定
JST = pytz.timezone('Asia/Tokyo')

# 絶対パスの設定
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

app.static_folder = STATIC_DIR
app.template_folder = TEMPLATES_DIR

# MySQLデータベースの設定
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://nikuya:Kids1109@nikuya.mysql.pythonanywhere-services.com/nikuya$nikuya_orders'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# カスタムフィルターの追加
@app.template_filter('fromjson')
def fromjson_filter(s):
    try:
        return json.loads(s) if s else []
    except (json.JSONDecodeError, TypeError):
        return []

@app.template_filter('get_menu_name')
def get_menu_name_filter(menu_id, course_name):
    """Jinja2フィルター：メニューIDからメニュー名を取得"""
    return get_menu_name_by_id(course_name, menu_id)

# 注文モデル
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seat_number = db.Column(db.Integer, nullable=False)
    course_name = db.Column(db.String(255), nullable=False)
    menu_items = db.Column(db.Text, nullable=False)  # JSON形式で保存
    order_time = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='cooking')  # 'cooking' or 'ok'
# 管理ページ
@app.route('/manage')
def manage():
    return render_template('manage.html')

# データベース初期化用エンドポイント
@app.route('/init_db')
def init_db():
    db.create_all()
    return "Database initialized!"

# 注文を保存するエンドポイント
@app.route('/order', methods=['POST'])
def order():
    try:
        print("=== ORDER ENDPOINT CALLED ===")
        data = request.get_json()
        print(f"Received data: {data}")
        
        seat_number = data.get('seat')
        course_name = data.get('course')
        menu_items = data.get('items')  # JSON形式のリスト
        
        print(f"Parsed - seat: {seat_number}, course: {course_name}, items: {menu_items}")

        if not seat_number or not course_name or not menu_items:
            print("Missing required fields")
            return jsonify({'success': False, 'error': 'Invalid order data'})

        # 注文をデータベースに保存
        new_order = Order(
            seat_number=seat_number,
            course_name=course_name,
            menu_items=json.dumps(menu_items)
        )
        print(f"Created order object: {new_order}")
        
        db.session.add(new_order)
        db.session.commit()
        print("Order saved to database successfully")

        return jsonify({'success': True, 'message': 'Order placed successfully!'})
    except Exception as e:
        print(f"Error in order endpoint: {e}")
        return jsonify({'success': False, 'error': str(e)})

# スタッフページ用エンドポイント
@app.route('/staff')
def staff():
    # スタッフページの処理
    orders = Order.query.order_by(Order.order_time.desc()).all()
    return render_template('staff.html', orders=orders, expired_seats=expired_seats)

# 席番号リスト
SEATS = [21,22,23,24,25,31,32,33,34,35,36,37,38,41,42,43,44,45,46,47,48,51,52,53]

# コースメニューの読み込み
def load_course_menus():
    data_dir = os.path.join(BASE_DIR, 'menus')  # JSONファイルの格納先
    course_menus = {}
    
    for filename in os.listdir(data_dir):
        if filename.endswith('.json'):
            course_id = os.path.splitext(filename)[0]  # 例: otameshi
            with open(os.path.join(data_dir, filename), encoding='utf-8') as f:
                course_menus[course_id] = json.load(f)
    
    return course_menus


COURSE_MENUS = load_course_menus()

# メニューIDからメニュー名を取得するヘルパー関数
def get_menu_name_by_id(course_name, menu_id):
    """
    コース名とメニューIDからメニュー名を取得
    """
    try:
        print(f"Looking for menu: course_name='{course_name}', menu_id='{menu_id}'")
        
        # コース名からコースIDを探す
        course_id = None
        for c_id, c_data in COURSE_MENUS.items():
            if c_data.get('course_name') == course_name:
                course_id = c_id
                break
        
        if not course_id:
            print(f"Course not found: {course_name}")
            return f"不明なメニュー ({menu_id})"
        
        print(f"Found course_id: {course_id}")
        course_data = COURSE_MENUS[course_id]
        
        if 'dishes_' in course_data:
            # カテゴリー内のアイテムを検索
            for category, items in course_data['dishes_'].items():
                for item in items:
                    if item.get('id') == menu_id:
                        menu_name = item.get('name', f"不明なメニュー ({menu_id})")
                        print(f"Found menu: {menu_name}")
                        return menu_name
        
        print(f"Menu not found in dishes: {menu_id}")
        return f"不明なメニュー ({menu_id})"
    except Exception as e:
        print(f"Error getting menu name: {e}")
        return f"不明なメニュー ({menu_id})"

# 注文データ保存用
orders = []  # [{seat, course_name, menu_id, quantity, time, expired, checked}]
expired_seats = []  # [{seat, expired_time, is_order_time}]
seat_timers = {}  # {seat: {order_end: datetime, seat_end: datetime}}
seat_courses = {}  # {seat: selected_course}

def get_course_times(course_id):
    """コースの注文時間と席時間を取得"""
    if course_id in COURSE_MENUS:
        course_data = COURSE_MENUS[course_id]
        order_time = course_data.get('order_time', 80)
        seat_time = course_data.get('seat_time', 20)
        
        # コンちゃんコースの特別ルール：金土日は80分・20分
        if course_id == "kon":
            now = datetime.now(JST)
            # 金曜日は4、土曜日は5、日曜日は6
            if now.weekday() in [4, 5, 6]:  # 金土日
                return 80, 20
        
        return order_time, seat_time
    
    # デフォルトの時間を返す
    return 80, 20

def format_jst_time(dt):
    """日本時間でフォーマット"""
    jst_time = dt.astimezone(JST)
    return jst_time.strftime('%H:%M')

def reset_daily_orders():
    """深夜0時に注文履歴をリセット"""
    try:
        print(f"=== DAILY ORDER RESET START at {datetime.now(JST)} ===")
        
        # データベースの注文履歴をクリア
        deleted_count = Order.query.delete()
        db.session.commit()
        
        print(f"Deleted {deleted_count} orders from database")
        print("=== DAILY ORDER RESET COMPLETED ===")
        
    except Exception as e:
        print(f"Error during daily reset: {e}")
        db.session.rollback()

def start_daily_reset_scheduler():
    """毎日深夜0時に注文をリセットするスケジューラーを開始"""
    def scheduler_thread():
        while True:
            try:
                now = datetime.now(JST)
                
                # 次の深夜0時を計算
                next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                
                # 次の実行までの秒数を計算
                seconds_until_midnight = (next_midnight - now).total_seconds()
                
                print(f"Next order reset scheduled at: {next_midnight.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Waiting {seconds_until_midnight} seconds...")
                
                # 深夜0時まで待機
                time.sleep(seconds_until_midnight)
                
                # 注文をリセット
                reset_daily_orders()
                
            except Exception as e:
                print(f"Error in scheduler thread: {e}")
                time.sleep(3600)  # エラー時は1時間後に再試行
    
    # デーモンスレッドとして開始
    thread = threading.Thread(target=scheduler_thread, daemon=True, name="daily_reset_scheduler")
    thread.start()
    print("Daily reset scheduler started")

def get_seat_status(seat):
    """席の状態を取得"""
    now = datetime.now(JST)
    
    if seat not in seat_timers:
        return 'no_timer'  # タイマーなし
    
    order_end = seat_timers[seat]['order_end']
    seat_end = seat_timers[seat]['seat_end']
    
    if now > seat_end:
        return 'expired'  # 席時間終了
    elif now > order_end:
        return 'order_expired'  # 注文時間終了
    else:
        return 'active'  # アクティブ

@app.route('/')
def index():
    seats_path = os.path.join(BASE_DIR, 'seats.json')
    if os.path.exists(seats_path):
        with open(seats_path, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = SEATS
    return render_template('index.html', seats=seats)

@app.route('/seat/<int:seat>')
def select_course(seat):
    seats_path = os.path.join(BASE_DIR, 'seats.json')
    if os.path.exists(seats_path):
        with open(seats_path, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = SEATS
    if seat not in seats:
        return redirect(url_for('index'))

    # 席の状態をチェック
    status = get_seat_status(seat)

    if status == 'active':
        # タイマーがアクティブな場合はメニューページにリダイレクト
        return redirect(url_for('menu', seat=seat))
    elif status == 'expired':
        # 席時間が終了している場合は会計案内
        return render_template('checkout_notice.html', seat=seat)

    # タイマーなし、または注文時間終了の場合はコース選択を表示
    return render_template('select_course.html', seat=seat, courses=COURSE_MENUS)

@app.route('/menu/<int:seat>')
def menu(seat):
    seats_path = os.path.join(BASE_DIR, 'seats.json')
    if os.path.exists(seats_path):
        with open(seats_path, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = SEATS
    if seat not in seats:
        return redirect(url_for('index'))

    # 席の状態をチェック
    status = get_seat_status(seat)

    if status == 'no_timer':
        # タイマーがない場合はコース選択にリダイレクト
        return redirect(url_for('select_course', seat=seat))
    elif status == 'expired':
        # 席時間が終了している場合は会計案内
        return render_template('checkout_notice.html', seat=seat)
    elif status == 'order_expired':
        # 注文時間が終了している場合は注文不可の案内
        return render_template('order_closed.html', seat=seat)

    # コースが選択されていない場合はコース選択画面にリダイレクト
    if seat not in seat_courses:
        return redirect(url_for('select_course', seat=seat))

    selected_course = COURSE_MENUS[seat_courses[seat]]

    # 現在の時刻（JST）
    now = datetime.now(JST)

    # タイマー情報
    timer_info = None
    if seat in seat_timers:
        timer_info = {
            'order_end': seat_timers[seat]['order_end'],
            'seat_end': seat_timers[seat]['seat_end'],
            'is_order_expired': now > seat_timers[seat]['order_end'],
            'is_seat_expired': now > seat_timers[seat]['seat_end']
        }

    return render_template('menu.html', 
                         seat=seat, 
                         course=selected_course,
                         timer_info=timer_info)

@app.route('/select_course', methods=['POST'])
def set_course():
    seat = int(request.form['seat'])
    course_id = request.form['course_name']  # 実際にはコースIDが送信される
    
    if seat not in SEATS or course_id not in COURSE_MENUS:
        return jsonify({'success': False, 'error': '無効な席番号またはコースIDです'})
    
    # コースを選択（コースIDを保存）
    seat_courses[seat] = course_id
    
    # コースの時間を取得
    order_time, seat_time = get_course_times(course_id)
    
    # タイマーを開始
    now = datetime.now(JST)
    order_end = now + timedelta(minutes=order_time)
    seat_end = order_end + timedelta(minutes=seat_time)
    
    seat_timers[seat] = {
        'order_end': order_end,
        'seat_end': seat_end
    }
    
    # 既存のタイマースレッドを停止（もし存在すれば）
    for thread in threading.enumerate():
        if isinstance(thread, threading.Thread) and thread.name == f"timer_{seat}":
            thread.join(timeout=0.1)
    
    # 新しいタイマースレッドを開始
    timer_thread_obj = threading.Thread(
        target=timer_thread,
        args=(seat,),
        daemon=True,
        name=f"timer_{seat}"
    )
    timer_thread_obj.start()
    
    # スタッフページに通知
    for thread in threading.enumerate():
        if isinstance(thread, threading.Thread) and thread.name == "staff_update":
            thread.join(timeout=0.1)

    staff_update_thread = threading.Thread(
        target=timer_thread,
        args=(seat,),
        daemon=True,
        name="staff_update"
    )
    staff_update_thread.start()
    
    # メニューページにリダイレクト
    return jsonify({
        'success': True,
        'redirect': url_for('menu', seat=seat)
    })

@app.route('/order_check', methods=['POST'])
def order_check():
    index = int(request.form['index'])
    checked = request.form['checked'] == 'true'

    if 0 <= index < len(orders):
        orders[index]['checked'] = checked
        return jsonify({'success': True})

    return jsonify({'success': False, 'error': '無効なインデックスです'})

@app.route('/toggle_order_status', methods=['POST'])
def toggle_order_status():
    try:
        data = request.get_json()
        order_id = data.get('order_id')
        completed = data.get('completed', False)
        
        # データベースの注文状態を更新
        order = Order.query.get(order_id)
        if order:
            order.status = 'ok' if completed else 'cooking'
            db.session.commit()
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': '注文が見つかりません'})
    except Exception as e:
        print(f"Error updating order status: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/reset_timer/<int:seat>', methods=['POST'])
def reset_timer(seat):
    seats_path = os.path.join(BASE_DIR, 'seats.json')
    if os.path.exists(seats_path):
        with open(seats_path, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = SEATS
    if seat not in seats:
        return jsonify({'success': False, 'error': '無効な席番号です'})

    # タイマーをリセット（削除）
    if seat in seat_timers:
        del seat_timers[seat]

    # コース選択をリセット
    if seat in seat_courses:
        del seat_courses[seat]

    # 既存のタイマースレッドを停止（もし存在すれば）
    for thread in threading.enumerate():
        if isinstance(thread, threading.Thread) and thread.name == f"timer_{seat}":
            thread.join(timeout=0.1)

    # expired_seatsから該当の席を削除
    global expired_seats
    expired_seats = [s for s in expired_seats if s['seat'] != seat]

    # 注文リストの該当席のexpiredフラグをリセット
    for o in orders:
        if o['seat'] == seat:
            o['expired'] = False

    return jsonify({'success': True})

@app.route('/staff_data')
def staff_data():
    sorted_orders = sorted(orders, key=lambda x: x['time'], reverse=True)
    expired = expired_seats
    now = datetime.now(JST)
    
    # 各席のタイマー情報を取得（アクティブなタイマーのみ）
    timer_info = {}
    for seat in SEATS:
        if seat in seat_timers:
            order_remaining = seat_timers[seat]['order_end'] - now
            seat_remaining = seat_timers[seat]['seat_end'] - now
            
            # アクティブなタイマーがある場合のみ追加
            if order_remaining.total_seconds() > 0 or seat_remaining.total_seconds() > 0:
                order_minutes = max(0, int(order_remaining.total_seconds() / 60))
                order_seconds = max(0, int(order_remaining.total_seconds() % 60))
                seat_minutes = max(0, int(seat_remaining.total_seconds() / 60))
                seat_seconds = max(0, int(seat_remaining.total_seconds() % 60))
                
                # コースIDからコース名を取得
                course_id = seat_courses.get(seat, None)
                course_name = None
                if course_id and course_id in COURSE_MENUS:
                    course_name = COURSE_MENUS[course_id].get('course_name', course_id)
                
                timer_info[seat] = {
                    'active': True,
                    'order_remaining_minutes': order_minutes,
                    'order_remaining_seconds': order_seconds,
                    'seat_remaining_minutes': seat_minutes,
                    'seat_remaining_seconds': seat_seconds,
                    'order_end_time': format_jst_time(seat_timers[seat]['order_end']),
                    'seat_end_time': format_jst_time(seat_timers[seat]['seat_end']),
                    'course': course_name
                }
    
    def serialize_order(o):
        course = COURSE_MENUS[o['course_name']]
        menu_item = None

        # dishes_を辞書として扱い、カテゴリー内のアイテムを検索
        for category, items in course['dishes_'].items():
            menu_item = next((item for item in items if item['id'] == o['menu_id']), None)
            if menu_item:
                break

        menu_name = menu_item['name'] if menu_item else '不明なメニュー'

        return {
            'seat': o['seat'],
            'course_name': course['course_name'],
            'menu_id': o['menu_id'],
            'menu_name': menu_name,
            'quantity': o['quantity'],
            'time': format_jst_time(o['time']),
            'expired': o['expired'],
            'checked': o['checked']
        }
    
    return jsonify({
        'orders': [serialize_order(o) for o in sorted_orders],
        'expired_seats': [{
            'seat': s['seat'],
            'expired_time': format_jst_time(s['expired_time']),
            'is_order_time': s.get('is_order_time', True)
        } for s in expired],
        'timer_info': timer_info
    })

def timer_thread(seat):
    """タイマースレッド関数"""
    while True:
        if seat not in seat_timers:
            break
        
        now = datetime.now(JST)
        order_end = seat_timers[seat]['order_end']
        seat_end = seat_timers[seat]['seat_end']
        
        # 注文時間切れのチェック
        if now >= order_end:
            # まだ記録されていない場合のみ記録
            if not any(s['seat'] == seat and s.get('is_order_time', True) for s in expired_seats):
                expired_seats.append({
                    'seat': seat,
                    'expired_time': now,
                    'is_order_time': True
                })
                # 該当席の注文を全て期限切れにする
                for order in orders:
                    if order['seat'] == seat:
                        order['expired'] = True
        
        # 席時間切れのチェック
        if now >= seat_end:
            # まだ記録されていない場合のみ記録
            if not any(s['seat'] == seat and not s.get('is_order_time', True) for s in expired_seats):
                expired_seats.append({
                    'seat': seat,
                    'expired_time': now,
                    'is_order_time': False
                })
            # 両方のタイマーが切れたらタイマーを削除
            del seat_timers[seat]
            break
        
        time.sleep(1)  # 1秒ごとにチェック

@app.route('/menu/<course_id>')
def show_menu(course_id):
    if course_id in COURSE_MENUS:
        course_data = COURSE_MENUS[course_id]
        return render_template('menu.html', course=course_data)
    else:
        return "Course not found", 404

@app.route('/timer_update', methods=['GET'])
def timer_update():
    now = datetime.now(JST)
    timer_info = {}
    for seat, timers in seat_timers.items():
        order_remaining = timers['order_end'] - now
        seat_remaining = timers['seat_end'] - now
        
        # アクティブなタイマーがある場合のみ追加
        if order_remaining.total_seconds() > 0 or seat_remaining.total_seconds() > 0:
            timer_info[seat] = {
                'order_remaining_minutes': max(0, int(order_remaining.total_seconds() / 60)),
                'order_remaining_seconds': max(0, int(order_remaining.total_seconds() % 60)),
                'seat_remaining_minutes': max(0, int(seat_remaining.total_seconds() / 60)),
                'seat_remaining_seconds': max(0, int(seat_remaining.total_seconds() % 60)),
                'order_end_time': format_jst_time(timers['order_end']),
                'seat_end_time': format_jst_time(timers['seat_end']),
            }

    return jsonify(timer_info)

@app.route('/create_order_table', methods=['GET'])
def create_order_table():
    try:
        # SQLAlchemyを使用してテーブルを作成
        db.create_all()
        return "Order table created successfully!"
    except Exception as e:
        return f"An error occurred: {e}"

# add_orderエンドポイントの修正
@app.route('/add_order', methods=['POST'])
def add_order():
    try:
        seat_number = request.form['seat_number']
        course_name = request.form['course_name']

        # SQLAlchemyを使用して注文を追加
        new_order = Order(seat_number=seat_number, course_name=course_name, menu_items="[]")
        db.session.add(new_order)
        db.session.commit()

        return jsonify({"success": True, "message": "Order added successfully!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# get_ordersエンドポイントの修正
@app.route('/get_orders', methods=['GET'])
def get_orders():
    try:
        # SQLAlchemyを使用して注文を取得（新しい順）
        orders = Order.query.order_by(Order.order_time.desc()).all()
        orders_list = []
        
        for order in orders:
            # メニューアイテムを解析してメニュー名を取得
            menu_items = json.loads(order.menu_items)
            menu_items_with_names = []
            
            for item in menu_items:
                menu_name = get_menu_name_by_id(order.course_name, item.get('id'))
                menu_items_with_names.append({
                    'id': item.get('id'),
                    'name': menu_name,
                    'quantity': item.get('quantity')
                })
            
            orders_list.append({
                "id": order.id,
                "seat_number": order.seat_number,
                "course_name": order.course_name,
                "menu_items": menu_items_with_names,
                "order_time": order.order_time.strftime('%Y-%m-%d %H:%M:%S'),
                "status": order.status
            })
        
        return jsonify(orders_list)
    except Exception as e:
        print(f"Error in get_orders: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/reset_orders', methods=['POST'])
def reset_orders():
    """注文履歴を手動でリセット（管理者用）"""
    try:
        deleted_count = Order.query.delete()
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'{deleted_count}件の注文履歴を削除しました',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


# ===== 管理API: 座席 =====
SEATS_JSON = os.path.join(BASE_DIR, 'seats.json')

@app.route('/api/seats', methods=['GET'])
def api_get_seats():
    if os.path.exists(SEATS_JSON):
        with open(SEATS_JSON, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = []
    return jsonify(seats)

@app.route('/api/seats', methods=['POST'])
def api_add_seat():
    data = request.get_json()
    seat = data.get('seat')
    if not seat:
        return jsonify({'success': False, 'error': 'seat番号必須'})
    if os.path.exists(SEATS_JSON):
        with open(SEATS_JSON, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = []
    if seat in seats:
        return jsonify({'success': False, 'error': '既に存在します'})
    seats.append(seat)
    with open(SEATS_JSON, 'w', encoding='utf-8') as f:
        json.dump(seats, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

@app.route('/api/seats/<int:seat>', methods=['PUT'])
def api_edit_seat(seat):
    data = request.get_json()
    new_seat = data.get('seat')
    if os.path.exists(SEATS_JSON):
        with open(SEATS_JSON, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = []
    if seat not in seats:
        return jsonify({'success': False, 'error': '存在しません'})
    idx = seats.index(seat)
    seats[idx] = new_seat
    with open(SEATS_JSON, 'w', encoding='utf-8') as f:
        json.dump(seats, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

@app.route('/api/seats/<int:seat>', methods=['DELETE'])
def api_delete_seat(seat):
    if os.path.exists(SEATS_JSON):
        with open(SEATS_JSON, encoding='utf-8') as f:
            seats = json.load(f)
    else:
        seats = []
    if seat not in seats:
        return jsonify({'success': False, 'error': '存在しません'})
    seats.remove(seat)
    with open(SEATS_JSON, 'w', encoding='utf-8') as f:
        json.dump(seats, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

# ===== 管理API: コース =====
MENUS_DIR = os.path.join(BASE_DIR, 'menus')

@app.route('/api/courses', methods=['GET'])
def api_get_courses():
    courses = []
    for filename in os.listdir(MENUS_DIR):
        if filename.endswith('.json'):
            with open(os.path.join(MENUS_DIR, filename), encoding='utf-8') as f:
                data = json.load(f)
                course_id = os.path.splitext(filename)[0]
                courses.append({
                    'id': course_id,
                    'name': data.get('course_name', course_id),
                    'hidden': data.get('hidden', False)
                })
    return jsonify(courses)

@app.route('/api/courses', methods=['POST'])
def api_add_course():
    data = request.get_json()
    name = data.get('name')
    course_id = data.get('id')
    if not name or not course_id:
        return jsonify({'success': False, 'error': 'nameとid必須'})
    path = os.path.join(MENUS_DIR, f'{course_id}.json')
    if os.path.exists(path):
        return jsonify({'success': False, 'error': '既に存在します'})
    course_data = {
        'course_name': name,
        'dishes_': {},
        'hidden': False
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(course_data, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

@app.route('/api/courses/<course_id>', methods=['PUT'])
def api_edit_course(course_id):
    data = request.get_json()
    path = os.path.join(MENUS_DIR, f'{course_id}.json')
    if not os.path.exists(path):
        return jsonify({'success': False, 'error': '存在しません'})
    with open(path, encoding='utf-8') as f:
        course_data = json.load(f)
    if 'name' in data:
        course_data['course_name'] = data['name']
    if 'hidden' in data:
        course_data['hidden'] = data['hidden']
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(course_data, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

@app.route('/api/courses/<course_id>', methods=['DELETE'])
def api_delete_course(course_id):
    path = os.path.join(MENUS_DIR, f'{course_id}.json')
    if not os.path.exists(path):
        return jsonify({'success': False, 'error': '存在しません'})
    os.remove(path)
    return jsonify({'success': True})

# ===== 管理API: 商品 =====
@app.route('/api/dishes/<course_id>', methods=['GET'])
def api_get_dishes(course_id):
    path = os.path.join(MENUS_DIR, f'{course_id}.json')
    if not os.path.exists(path):
        return jsonify([])
    with open(path, encoding='utf-8') as f:
        course_data = json.load(f)
    dishes = []
    for category, items in course_data.get('dishes_', {}).items():
        for item in items:
            dishes.append({
                'category': category,
                'id': item.get('id'),
                'name': item.get('name'),
                'hidden': item.get('hidden', False)
            })
    return jsonify(dishes)

@app.route('/api/dishes/<course_id>', methods=['POST'])
def api_add_dish(course_id):
    data = request.get_json()
    category = data.get('category')
    dish_id = data.get('id')
    name = data.get('name')
    if not category or not dish_id or not name:
        return jsonify({'success': False, 'error': 'category, id, name必須'})
    path = os.path.join(MENUS_DIR, f'{course_id}.json')
    if not os.path.exists(path):
        return jsonify({'success': False, 'error': 'コースが存在しません'})
    with open(path, encoding='utf-8') as f:
        course_data = json.load(f)
    if category not in course_data['dishes_']:
        course_data['dishes_'][category] = []
    for item in course_data['dishes_'][category]:
        if item.get('id') == dish_id:
            return jsonify({'success': False, 'error': '既に存在します'})
    course_data['dishes_'][category].append({'id': dish_id, 'name': name, 'hidden': False})
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(course_data, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

@app.route('/api/dishes/<course_id>/<dish_id>', methods=['PUT'])
def api_edit_dish(course_id, dish_id):
    data = request.get_json()
    path = os.path.join(MENUS_DIR, f'{course_id}.json')
    if not os.path.exists(path):
        return jsonify({'success': False, 'error': 'コースが存在しません'})
    with open(path, encoding='utf-8') as f:
        course_data = json.load(f)
    found = False
    for category, items in course_data.get('dishes_', {}).items():
        for item in items:
            if item.get('id') == dish_id:
                if 'name' in data:
                    item['name'] = data['name']
                if 'hidden' in data:
                    item['hidden'] = data['hidden']
                found = True
    if not found:
        return jsonify({'success': False, 'error': '商品が存在しません'})
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(course_data, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

@app.route('/api/dishes/<course_id>/<dish_id>', methods=['DELETE'])
def api_delete_dish(course_id, dish_id):
    path = os.path.join(MENUS_DIR, f'{course_id}.json')
    if not os.path.exists(path):
        return jsonify({'success': False, 'error': 'コースが存在しません'})
    with open(path, encoding='utf-8') as f:
        course_data = json.load(f)
    removed = False
    for category, items in course_data.get('dishes_', {}).items():
        for i, item in enumerate(items):
            if item.get('id') == dish_id:
                del items[i]
                removed = True
                break
    if not removed:
        return jsonify({'success': False, 'error': '商品が存在しません'})
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(course_data, f, ensure_ascii=False, indent=2)
    return jsonify({'success': True})

if __name__ == '__main__':
    # 日次リセットスケジューラーを開始
    start_daily_reset_scheduler()
    
    # PythonAnywhereではデバッグモードを無効化
    app.run()