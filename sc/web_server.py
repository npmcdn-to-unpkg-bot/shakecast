from app.objects import AlchemyEncoder
from app.util import *
import os
import sys
import io
import json
modules_dir = os.path.join(sc_dir(), 'modules')
if modules_dir not in sys.path:
    sys.path += [modules_dir]

from flask import Flask, render_template, url_for, request, session, flash, redirect, send_file
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from flask_uploads import UploadSet, configure_uploads
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import time
import datetime
from ast import literal_eval
from app.orm import *
from app.server import Server
from app.objects import Clock, SC, NotificationBuilder
from app.functions import determine_xml
from ui import UI

app = Flask(__name__,
            template_folder=os.path.join(sc_dir(),'view','html'),
            static_folder=os.path.join(sc_dir(),'view','static'))

################################ Login ################################

app.secret_key = 'super secret key'
app.config['SESSION_TYPE'] = 'filesystem'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    session = Session()
    user = session.query(User).filter(User.shakecast_id==int(user_id)).first()
    
    Session.remove()
    return user

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    session = Session()
    username = request.form['username']
    password = request.form['password']
    
    registered_user = (session.query(User)
                            .filter(and_(User.username==username)).first())
    
    if (registered_user is None or not
            check_password_hash(registered_user.password, password)):
        Session.remove()
        return redirect('/#login-fail')

    login_user(registered_user)
    flash('Logged in successfully')
    Session.remove()
    return redirect(request.args.get('next') or url_for('index'))

@app.route('/logout')
def logout():
    logout_user()
    flash('Logged out successfully')
    return redirect(url_for('login'))

############################# User Domain #############################

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/earthquakes')
@login_required
def earthquakes():
    return render_template('earthquakes.html')

@app.route('/home')
@login_required
def home():
    return render_template('home.html')

@app.route('/get/eqdata')
@login_required
def get_eq_data():
    session = Session()
    filter_ = json.loads(request.args.get('filter', '{}'))
    DAY = 24*60*60
    
    query = session.query(Event)
    if filter_:
        if filter_.get('group', None):
            query = query.filter(Event.groups.any(Group.name.like(filter_['group'])))
        if filter_.get('lat_max', None):
            query = query.filter(Event.lat < filter_['lat_max'])
        if filter_.get('lat_min', None):
            query = query.filter(Event.lat > filter_['lat_min'])
        if filter_.get('lon_max', None):
            query = query.filter(Event.lon < filter_['lon_max'])
        if filter_.get('lon_min', None):
            query = query.filter(Event.lat > filter_['lon_min'])

        if filter_.get('timeframe', None):
            timeframe = filter_.get('timeframe')
            if timeframe == 'day':
                query = query.filter(Event.time > time.time() - DAY)
            elif timeframe == 'week':
                query = query.filter(Event.time > time.time() - 7*DAY)    
            elif timeframe == 'month':
                query = query.filter(Event.time > time.time() - 31*DAY)    
            elif timeframe == 'year':
                query = query.filter(Event.time > time.time() - 365*DAY)    
        if filter_.get('all_events', False) is False:
            query = query.filter(Event.shakemaps)
    
    # get the time of the last earthquake in UI,
    # should be 0 for a new request
    eq_time = float(request.args.get('time', 0))
    if eq_time < 1:
        eq_time = time.time()
        
    eqs = (query.filter(Event.time < eq_time)
                .filter(Event.event_id != 'heartbeat')
                .order_by(desc(Event.time))
                .limit(50)
                .all())
    
    eq_dicts = []
    for eq in eqs:
        eq_dict = eq.__dict__.copy()
        eq_dict.pop('_sa_instance_state', None)
        eq_dicts += [eq_dict]
    
    eq_json = json.dumps(eq_dicts, cls=AlchemyEncoder)
    
    Session.remove()    
    return eq_json

@app.route('/get/shakemaps')
@login_required
def get_shakemaps():
    session = Session()
    sms = (session.query(ShakeMap)
                .order_by(ShakeMap.recieve_timestamp.desc())
                .all())
    
    sm_dicts = []
    for sm in sms:
        sm_dict = sm.__dict__.copy()
        sm_dict.pop('_sa_instance_state', None)
        sm_dicts += [sm_dict]
    
    sm_json = json.dumps(sm_dicts, cls=AlchemyEncoder)
    
    Session.remove()    
    return sm_json

@app.route('/get/shakemaps/<shakemap_id>')
@login_required
def get_shakemap(shakemap_id):
    session = Session()
    sms = (session.query(ShakeMap)
                .filter(ShakeMap.shakemap_id == shakemap_id)
                .order_by(ShakeMap.shakemap_version.desc())
                .all())
    
    sm_dicts = []
    for sm in sms:
        sm_dict = sm.__dict__.copy()
        sm_dict.pop('_sa_instance_state', None)
        sm_dicts += [sm_dict]
    
    sm_json = json.dumps(sm_dicts, cls=AlchemyEncoder)
    
    Session.remove()    
    return sm_json

@app.route('/get/shakemaps/<shakemap_id>/facilities')
@login_required
def get_affected_facilities(shakemap_id):
    session = Session()
    sms = (session.query(ShakeMap)
                .filter(ShakeMap.shakemap_id == shakemap_id)
                .order_by(ShakeMap.shakemap_version.desc())
                .all())
    
    fac_dicts = []
    if sms:
        sm = sms[0]
        fac_shaking = sm.facility_shaking
        
        for s in fac_shaking:
            fac_dict = s.facility.__dict__.copy()
            s_dict = s.__dict__.copy()
            fac_dict.pop('_sa_instance_state', None)
            s_dict.pop('_sa_instance_state', None)
            fac_dict['shaking'] = s_dict
            fac_dicts += [fac_dict]
    
    fac_json = json.dumps(fac_dicts, cls=AlchemyEncoder)
    
    Session.remove()    
    return fac_json

@app.route('/get/shakemaps/<shakemap_id>/overlay')
@login_required
def shakemap_overlay(shakemap_id):
    session = Session()
    shakemap = (session.query(ShakeMap)
                    .filter(ShakeMap.shakemap_id == shakemap_id)
                    .order_by(desc(ShakeMap.shakemap_version))
                    .limit(1)).first()
    if shakemap is not None:
        img = os.path.join(app.config['EARTHQUAKES'],
                           shakemap_id,
                           shakemap_id + '-' + str(shakemap.shakemap_version),
                           'ii_overlay.png')
        
    else:
        img = app.send_static_file('sc_logo.png')
        
    Session.remove()
    return send_file(img, mimetype='image/gif')

@app.route('/get/shakemaps/<shakemap_id>/shakemap')
@login_required
def shakemap_map(shakemap_id):
    session = Session()
    shakemap = (session.query(ShakeMap)
                    .filter(ShakeMap.shakemap_id == shakemap_id)
                    .order_by(desc(ShakeMap.shakemap_version))
                    .limit(1)).first()
    if shakemap is not None:
        img = shakemap.get_map()

    return send_file(io.BytesIO(img), mimetype='image/png')

@app.route('/get/events/<event_id>/image')
@login_required
def event_image(event_id):
    session = Session()
    event = (session.query(Event)
                    .filter(Event.event_id == event_id)
                    .limit(1)).first()
    if event is not None:
        img = os.path.join(app.config['EARTHQUAKES'],
                           event_id,
                           'image.png')
        
    else:
        img = app.send_static_file('sc_logo.png')
        
    Session.remove()
    return send_file(img, mimetype='image/gif')

############################ Admin Pages ##############################

# wrapper for admin only URLs
def admin_only(func):
    @wraps(func)
    def func_wrapper(*args, **kwargs):
        if current_user and current_user.is_authenticated:
            if current_user.user_type.lower() == 'admin':
                return func(*args, **kwargs)
            else:
                flash('Only administrators can access this page')
                return redirect(url_for('index'))
        else:
            flash('Login as an administrator to access this page')
            return redirect(url_for('login'))
    return func_wrapper

@app.route('/admin/')
@admin_only
@login_required
def admin():
    return render_template('admin/admin.html')

@app.route('/admin/settings/', methods=['GET','POST'])
@admin_only
@login_required
def settings():
    if request.method == 'GET':
        return render_template('admin/settings.html')
    sc = SC()
    settings = request.get_json().get('settings', '')
    sc.json = json.dumps(settings)
    
    if sc.validate() is True:
        sc.save()
        return redirect('/admin/#/settings/')

@app.route('/admin/inventory/')
@admin_only
@login_required
def inventory():
    return render_template('admin/inventory.html')

@app.route('/admin/users/')
@admin_only
@login_required
def users():
    return render_template('admin/users.html')

@app.route('/admin/groups/')
@admin_only
@login_required
def groups():
    return render_template('admin/groups.html')

@app.route('/admin/upload/', methods=['GET','POST'])
@admin_only
@login_required
def upload():
    if request.method == 'GET':
        return render_template('admin/upload.html')
    
    xml_files.save(request.files['file'])
    xml_file = os.path.join(app.config['UPLOADED_XMLFILES_DEST'],
                            request.files['file'].filename)
    # validate XML and determine which import function should be used
    xml_file_type = determine_xml(xml_file)
    
    # these import functions need to be submitted to the server instead
    # of run directly
    import_data = {}
    if xml_file_type is 'facility':
        ui.send("{'import_facility_xml': {'func': import_facility_xml, \
                                          'args_in': {'xml_file': r'%s'}, \
                                          'db_use': True, \
                                          'loop': False}}" % xml_file)

    if xml_file_type is 'group':
        send_str = ("{'import_group_xml': {'func': import_group_xml, \
                                          'args_in': {'xml_file': r'%s'}, \
                                          'db_use': True, \
                                          'loop': False}}" % xml_file)
        ui.send(send_str)
    if xml_file_type is 'user':
        ui.send("{'import_user_xml': {'func': import_user_xml, \
                                          'args_in': {'xml_file': r'%s'}, \
                                          'db_use': True, \
                                          'loop': False}}" % xml_file)
    else:
        import_data = {'error': 'root'}
        
    return 'file uploaded'

@app.route('/admin/notification', methods=['GET','POST'])
@admin_only
@login_required
def notification():
    return render_template('admin/notification.html')

@app.route('/admin/get/notification/<group_id>/<notification_type>', methods=['GET','POST'])
@admin_only
@login_required
def notification_html(group_id, notification_type):
    session = Session()
    not_builder = NotificationBuilder()

    if notification_type == 'new_event':
        # get the two most recent events
        events = session.query(Event).all()
        events = events[-2:]
        html = not_builder.build_new_event_html(events=events, web=True)
    else:
        # get the most recent shakemap
        sms = session.query(ShakeMap).all()
        sm = sms[-1]
        html = not_builder.build_insp_html(sm, web=True)
    Session.remove()
    return html

@app.route('/admin/earthquakes')
@admin_only
@login_required
def admin_eqs():
    return render_template('admin/earthquakes.html')

@app.route('/admin/get/groups')
@admin_only
@login_required
def get_groups():
    session = Session()
    groups = (session.query(Group)
                .filter(Group.shakecast_id > request.args.get('last_id', 0))
                .limit(50)
                .all())
    
    group_dicts = []
    for group in groups:
        group_dict = group.__dict__.copy()
        group_dict.pop('_sa_instance_state', None)
        group_dicts += [group_dict]
        
    group_json = json.dumps(group_dicts, cls=AlchemyEncoder)
    
    Session.remove()    
    return group_json

@app.route('/admin/get/groups/<group_id>/specs')
@admin_only
@login_required
def get_group_specs(group_id):
    session = Session()
    group = (session.query(Group)
                .filter(Group.shakecast_id == group_id)
                .first())
    
    group_specs = {'inspection': [],
                   'new_event': [],
                   'heartbeat': [],
                   'scenario_inspection': [],
                   'scenario_new_event': []}
    if group is not None:
        for spec in group.specs:
            if spec.notification_type is not None and spec.event_type is not None:
                spec_dict = spec.__dict__.copy()
                spec_dict.pop('_sa_instance_state', None)
                if spec.notification_type.lower() == 'damage' and spec.event_type.lower() == 'actual':
                    group_specs['inspection'] += [spec_dict]
                elif spec.notification_type.lower() == 'new_event' and spec.event_type.lower() == 'actual':
                    group_specs['new_event'] += [spec_dict]
                elif spec.notification_type.lower() == 'damage' and spec.event_type.lower() =='scenario':
                    group_specs['scenario_inspection'] += [spec_dict]
                elif spec.notification_type.lower() == 'new_event' and spec.event_type.lower() =='scenario':
                    group_specs['scenario_new_event'] += [spec_dict]
                elif spec.notification_type.lower() == 'heartbeat':
                    group_specs['heartbeat'] += [spec_dict]
    
    specs_json = json.dumps(group_specs, cls=AlchemyEncoder)
    
    Session.remove()    
    return specs_json

@app.route('/admin/get/users')
@admin_only
@login_required
def get_users():
    session = Session()
    filter_ = literal_eval(request.args.get('filter', 'None'))
    if filter_:
        if filter_.get('group', None):
            users = (session.query(User)
                            .filter(User.shakecast_id > request.args.get('last_id', 0))
                            .filter(User.groups.any(Group.name.like(filter_['group'])))
                            .limit(50)
                            .all())
            
        else:
            users = (session.query(User)
                            .filter(User.shakecast_id > request.args.get('last_id', 0))
                            .limit(50)
                            .all())
    else:   
        users = session.query(User).filter(User.shakecast_id > request.args.get('last_id', 0)).limit(50).all()
    
    user_dicts = []
    for user in users:
        user_dict = user.__dict__.copy()
        user_dict.pop('_sa_instance_state', None)
        user_dicts += [user_dict]
        
    user_json = json.dumps(user_dicts, cls=AlchemyEncoder)
    
    Session.remove()    
    return user_json

@app.route('/admin/get/users/<user_id>/groups')
@admin_only
@login_required
def get_user_groups(user_id):
    session = Session()
    user = session.query(User).filter(User.shakecast_id == user_id).first()
    
    groups = []
    if user is not None and user.groups:
        for group in user.groups:
            group_dict = group.__dict__.copy()
            group_dict.pop('_sa_instance_state', None)
            groups += [group_dict]
    
    groups_json = json.dumps(groups, cls=AlchemyEncoder)
    
    Session.remove()    
    return groups_json

@app.route('/admin/get/inventory')
@admin_only
@login_required
def get_inventory():
    session = Session()
    filter_ = json.loads(request.args.get('filter', '{}'))
    if filter_:
        if filter_.get('group', None) is not None:
            facilities = (session.query(Facility)
                            .filter(Facility.shakecast_id > request.args.get('last_id', 0))
                            .filter(Facility.lat_min > (float(filter_['lat']) - float(filter_['lat_pm'])))
                            .filter(Facility.lat_max < (float(filter_['lat']) + float(filter_['lat_pm'])))
                            .filter(Facility.lon_min > (float(filter_['lon']) - float(filter_['lon_pm'])))
                            .filter(Facility.lon_max < (float(filter_['lon']) + float(filter_['lon_pm'])))
                            .filter(Facility.groups.any(Group.name.like(filter_['group'])))
                            .limit(50)
                            .all())
            
        else:
            facilities = (session.query(Facility)
                            .filter(Facility.shakecast_id > request.args.get('last_id', 0))
                            .filter(Facility.lat_min > (float(filter_['lat']) - float(filter_['lat_pm'])))
                            .filter(Facility.lat_max < (float(filter_['lat']) + float(filter_['lat_pm'])))
                            .filter(Facility.lon_min > (float(filter_['lon']) - float(filter_['lon_pm'])))
                            .filter(Facility.lon_max < (float(filter_['lon']) - float(filter_['lon_pm'])))
                            .limit(50)
                            .all())
    else:   
        facilities = session.query(Facility).filter(Facility.shakecast_id > request.args.get('last_id', 0)).limit(50).all()
    
    facility_dicts = []
    for facility in facilities:
        facility_dict = facility.__dict__.copy()
        facility_dict.pop('_sa_instance_state', None)
        facility_dicts += [facility_dict]
    
    facilities_json = json.dumps(facility_dicts, cls=AlchemyEncoder)
    
    Session.remove()    
    return facilities_json

@app.route('/admin/get/settings')
@admin_only
@login_required
def get_settings():
    sc = SC()
    return sc.json

############################# Upload Setup ############################
app.config['UPLOADED_XMLFILES_DEST'] = os.path.join(sc_dir(), 'tmp')
app.config['EARTHQUAKES'] = os.path.join(sc_dir(), 'data')
xml_files = UploadSet('xmlfiles', ('xml',))
configure_uploads(app, (xml_files,))


if __name__ == '__main__':
    ui = UI()
    if len(sys.argv) > 1:
        if sys.argv[1] == '-d':
            # run in debug mode
            app.run(host='0.0.0.0', port=5000, debug=True)
    else:
        app.run(host='0.0.0.0', port=80)
