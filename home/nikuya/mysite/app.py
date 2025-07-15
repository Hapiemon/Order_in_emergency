from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime, timedelta
import threading
import time
import json
import os
import pytz

app = Flask(__name__)

# 日本のタイムゾーンを設定
JST = pytz.timezone('Asia/Tokyo')

# 絶対パスの設定
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

app.static_folder = STATIC_DIR
app.template_folder = TEMPLATES_DIR

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

# 注文データ保存用
orders = []  # [{seat, course_name, menu_id, quantity, time, expired, checked}]
expired_seats = []  # [{seat, expired_time, is_order_time}]
seat_timers = {}  # {seat: {order_end: datetime, seat_end: datetime}}
seat_courses = {}  # {seat: selected_course}

def get_course_times(course_id):
    """コースの注文時間と席時間を取得"""
    if course_id == "kon":
        # 現在の日本時間を取得
        now = datetime.now(JST)
        # 土曜日は5、日曜日は6
        if now.weekday() in [5, 6]:  # 週末
            return 90, 30
    # デフォルトの時間を返す
    return 80, 20

def format_jst_time(dt):
    """日本時間でフォーマット"""
    jst_time = dt.astimezone(JST)
    return jst_time.strftime('%H:%M')

@app.route('/')
def index():
    return render_template('index.html', seats=SEATS)

@app.route('/seat/<int:seat>')
def select_course(seat):
    if seat not in SEATS:
        return redirect(url_for('index'))
    return render_template('select_course.html', seat=seat, courses=COURSE_MENUS)

@app.route('/menu/<int:seat>')
def menu(seat):
    if seat not in SEATS:
        return redirect(url_for('index'))
    
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
    course_name = request.form['course_name']
    
    if seat not in SEATS or course_name not in COURSE_MENUS:
        return jsonify({'success': False, 'error': '無効な席番号またはコース名です'})
    
    # コースを選択
    seat_courses[seat] = course_name
    
    # コースの時間を取得
    order_time, seat_time = get_course_times(course_name)
    
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
    
    # メニューページにリダイレクト
    return jsonify({
        'success': True,
        'redirect': url_for('menu', seat=seat)
    })

@app.route('/order', methods=['POST'])
def order():
    seat = int(request.form['seat'])
    menu_id = request.form['menu_id']
    quantity = int(request.form['quantity'])
    course_name = seat_courses.get(seat)
    
    if not course_name:
        return jsonify({'success': False, 'error': 'コースが選択されていません'})
    
    # 注文時間が切れている場合は注文を受け付けない
    now = datetime.now(JST)
    if seat in seat_timers and now > seat_timers[seat]['order_end']:
        return jsonify({'success': False, 'error': '注文可能時間が終了しました'})
    
    orders.append({
        'seat': seat,
        'course_name': course_name,
        'menu_id': menu_id,
        'quantity': quantity,
        'time': now,
        'expired': False,
        'checked': False
    })
    return jsonify({'success': True})

@app.route('/staff')
def staff():
    # 新着順で注文を表示
    sorted_orders = sorted(orders, key=lambda x: x['time'], reverse=True)
    return render_template('staff.html', 
                         orders=sorted_orders, 
                         courses=COURSE_MENUS, 
                         expired_seats=expired_seats)

@app.route('/reset_timer/<int:seat>', methods=['POST'])
def reset_timer(seat):
    if seat not in SEATS:
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
    
    # 各席のタイマー情報を取得
    timer_info = {}
    for seat in SEATS:
        if seat in seat_timers:
            order_remaining = seat_timers[seat]['order_end'] - now
            seat_remaining = seat_timers[seat]['seat_end'] - now
            
            order_minutes = max(0, int(order_remaining.total_seconds() / 60))
            order_seconds = max(0, int(order_remaining.total_seconds() % 60))
            seat_minutes = max(0, int(seat_remaining.total_seconds() / 60))
            seat_seconds = max(0, int(seat_remaining.total_seconds() % 60))
            
            timer_info[seat] = {
                'active': order_remaining.total_seconds() > 0 or seat_remaining.total_seconds() > 0,
                'order_remaining_minutes': order_minutes,
                'order_remaining_seconds': order_seconds,
                'seat_remaining_minutes': seat_minutes,
                'seat_remaining_seconds': seat_seconds,
                'order_end_time': format_jst_time(seat_timers[seat]['order_end']),
                'seat_end_time': format_jst_time(seat_timers[seat]['seat_end']),
                'course': seat_courses.get(seat, None)
            }
        else:
            timer_info[seat] = {
                'active': False,
                'order_remaining_minutes': 0,
                'order_remaining_seconds': 0,
                'seat_remaining_minutes': 0,
                'seat_remaining_seconds': 0,
                'order_end_time': None,
                'seat_end_time': None,
                'course': seat_courses.get(seat, None)
            }
    
    def serialize_order(o):
        course = COURSE_MENUS[o['course_name']]
        menu_item = next((item for item in course['dishes_'] if item['id'] == o['menu_id']), None)
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

if __name__ == '__main__':
    app.run(debug=True) 