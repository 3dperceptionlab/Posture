"""RULA/REBA tables and preliminary geometry; not a validated vision measurement.

Table sources: McAtamney/Corlett 1993 and Hignett/McAtamney 2000,
Cornell RULA worksheet and Cornell_REBA slides. See docs/METRICAS.md.
"""
import math

VERSION = 'posture-ergonomics-0.1.0'
RULA_A = [
 [[1,2,2,2,2,3,3,3],[2,2,2,2,3,3,3,3],[2,3,2,3,3,3,4,4]],
 [[2,2,2,3,3,3,4,4],[2,2,2,3,3,3,4,4],[2,3,3,3,3,4,4,5]],
 [[2,3,3,3,4,4,5,5],[2,3,3,3,4,4,5,5],[2,3,3,4,4,4,5,5]],
 [[3,4,4,4,4,4,5,5],[3,4,4,4,4,4,5,5],[3,4,4,5,5,5,6,6]],
 [[5,5,5,5,5,6,6,7],[5,6,6,6,6,7,7,7],[6,6,6,7,7,7,7,8]],
 [[7,7,7,7,7,8,8,9],[7,8,8,8,8,9,9,9],[9,9,9,9,9,9,9,9]]]
RULA_B = [[1,3,2,3,3,4,5,5,6,6,7,7],[2,3,2,3,4,5,5,5,6,7,7,7],
 [3,3,3,4,4,5,5,6,6,7,7,7],[5,5,5,6,6,7,7,7,7,7,8,8],
 [7,7,7,7,7,8,8,8,8,8,8,8],[8,8,8,8,8,8,8,9,9,9,9,9]]
RULA_C = [[1,2,3,3,4,5,5],[2,2,3,4,4,5,5],[3,3,3,4,4,5,6],
 [3,3,3,4,5,6,6],[4,4,4,5,6,7,7],[4,4,5,6,6,7,7],[5,5,6,6,7,7,7],[5,5,6,7,7,7,7]]
REBA_A = [[1,2,3,4,1,2,3,4,3,3,5,6],[2,3,4,5,3,4,5,6,4,5,6,7],
 [2,4,5,6,4,5,6,7,5,6,7,8],[3,5,6,7,5,6,7,8,6,7,8,9],[4,6,7,8,6,7,8,9,7,8,9,9]]
REBA_B = [[1,2,3,1,2,3],[1,2,3,2,3,4],[3,4,5,4,5,5],
 [4,5,5,5,6,7],[6,7,8,7,8,8],[7,8,8,8,9,9]]
REBA_C = [[1,1,1,2,3,3,4,5,6,7,7,7],[1,2,2,3,4,4,5,6,6,7,7,8],
 [2,3,3,3,4,5,6,7,7,8,8,8],[3,4,4,4,5,6,7,8,8,9,9,9],
 [4,4,4,5,6,7,8,8,9,9,9,9],[6,6,6,7,8,8,9,9,10,10,10,10],
 [7,7,7,8,9,9,9,10,10,11,11,11],[8,8,8,9,10,10,10,10,10,11,11,11],
 [9,9,9,10,10,10,11,11,11,12,12,12],[10,10,10,11,11,11,11,12,12,12,12,12],
 [11,11,11,11,12,12,12,12,12,12,12,12],[12]*12]


def clamp(n, low, high):
    return max(low, min(high, n))


def angle(a, b):
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    if norm < 1e-9:
        return None
    return math.degrees(math.acos(clamp(sum(x*y for x,y in zip(a,b))/norm, -1, 1)))


def sub(a, b):
    return [x-y for x,y in zip(a,b)]


def mid(a, b):
    return [(x+y)/2 for x,y in zip(a,b)] if a and b else None


def score_rula(upper, lower, wrist, twist, neck, trunk, legs, muscle, load):
    a = RULA_A[clamp(upper,1,6)-1][clamp(lower,1,3)-1][(clamp(wrist,1,4)-1)*2+clamp(twist,1,2)-1]
    b = RULA_B[clamp(neck,1,6)-1][(clamp(trunk,1,6)-1)*2+clamp(legs,1,2)-1]
    return RULA_C[clamp(a+muscle+load,1,8)-1][clamp(b+muscle+load,1,7)-1]


def score_reba(upper, lower, wrist, neck, trunk, legs, load, coupling, activity):
    a = REBA_A[clamp(trunk,1,5)-1][(clamp(neck,1,3)-1)*4+clamp(legs,1,4)-1] + load
    b = REBA_B[clamp(upper,1,6)-1][(clamp(lower,1,2)-1)*3+clamp(wrist,1,3)-1] + coupling
    return clamp(REBA_C[clamp(a,1,12)-1][clamp(b,1,12)-1]+activity,1,15)


def compute(message, context):
    pose = message.get('pose')
    if not pose:
        return None
    joints = pose['joints']
    # Use the same coordinate source for every segment. No invented depth/gravity.
    space = pose.get('space_3d')
    needed = ['left_shoulder','right_shoulder','left_hip','right_hip','nose']
    metric3d = bool(space and space['kind'] in ('camera_metric','world_metric')
                    and space['frame_id'].endswith('_optical')
                    and all(joints[n].get('point_3d_m') for n in needed))
    field = 'point_3d_m' if metric3d else 'image_xy_px'
    def point(name):
        p = joints.get(name, {})
        if p.get('status') == 'missing' or (p.get('confidence') is not None and p['confidence'] < .5):
            return None
        return p.get(field)
    shoulders = mid(point('left_shoulder'), point('right_shoulder'))
    hips = mid(point('left_hip'), point('right_hip'))
    head = mid(point('left_ear'),point('right_ear')) or point('nose')
    up = [0,-1,0] if metric3d else [0,-1]
    torso = sub(shoulders,hips) if shoulders and hips else None
    trunk = angle(torso,up) if torso else None
    neck = angle(sub(head,shoulders),torso) if head and shoulders and torso else None
    angles = {'trunk': trunk, 'neck': neck}
    assumptions = ['Vista monocular: flexión/extensión y giro no validados.',
                   'Referencia vertical de imagen; cámara sin alineación gravitatoria validada.',
                   'Pies, equilibrio y rodillas fuera de observación completa.',
                   'Sin detección validada de elevación de hombro, abducción ni desviación de muñeca.']
    operation = context['operation']
    def value(name):
        item = operation[name]
        if item['provenance'] in ('assumed','unknown'):
            assumptions.append(f'{name}: {item["value"]} ({item["provenance"]})')
        return item['value']
    supported = value('upper_arm_supported')
    legs = 1 if value('feet_supported_and_balanced') else 2
    repeat = value('repetitions_ge_4_per_min')
    static = value('static_hold_over_60s')
    shock = value('shock_or_sudden_force')
    twist = 1 if value('wrist_twist') == 'midrange' else 2
    coupling = {'good':0,'fair':1,'poor':2,'unacceptable':3}.get(value('grip_quality'),1)
    # A task context, not an inferred safety measurement. Default to manual finishing.
    phase = message.get('_phase', 'manual_finishing')
    proxy = context['phases'].get(phase,context['phases']['manual_finishing'])['human_load_proxy_kg']
    mass = float(proxy['value'])
    assumptions.append(f'Carga proxy {phase}: {mass} kg ({proxy["provenance"]}); fuerza de corte no medida.')
    muscle = int(bool(repeat or static))
    load_rula = 3 if shock or mass > 10 else (2 if mass >= 2 and muscle else 1 if mass >= 2 else 0)
    load_reba = (2 if mass > 10 else 1 if mass >= 5 else 0) + int(bool(shock))
    sides = {}
    for side in ('left','right'):
        shoulder,elbow,wrist,finger = [point(side+'_'+n) for n in ('shoulder','elbow','wrist','index')]
        arm = angle(sub(elbow,shoulder),[-x for x in torso]) if elbow and shoulder and torso else None
        elbow_angle = angle(sub(shoulder,elbow),sub(wrist,elbow)) if shoulder and elbow and wrist else None
        elbow_flex = 180-elbow_angle if elbow_angle is not None else None
        wrist_angle = angle(sub(wrist,elbow),sub(finger,wrist)) if elbow and wrist and finger else None
        angles.update({f'{side}_upper_arm':arm,f'{side}_elbow_flexion':elbow_flex,f'{side}_wrist':wrist_angle})
        if any(v is None for v in (arm,elbow_flex,wrist_angle,trunk,neck)):
            sides[side] = {'rula':None,'reba':None,'reason':'Articulaciones necesarias ausentes, de baja confianza o degeneradas.'}
            continue
        u = clamp((1 if arm <=20 else 2 if arm <=45 else 3 if arm <=90 else 4)-int(bool(supported)),1,6)
        lo = 1 if 60<=elbow_flex<=100 else 2
        wr = 1 if wrist_angle <=1 else 2 if wrist_angle <=15 else 3
        n = 1 if neck<=10 else 2 if neck<=20 else 3
        t = 1 if trunk<=5 else 2 if trunk<=20 else 3 if trunk<=60 else 4
        rn = 1 if neck<=20 else 2
        rt = t
        rw = 1 if wrist_angle<=15 else 2
        sides[side] = {'rula':score_rula(u,lo,wr,twist,n,t,legs,muscle,load_rula),
            'reba':score_reba(u,lo,rw,rn,rt,legs,load_reba,coupling,int(bool(static))+int(bool(repeat))),
            'components':{'upper_arm':u,'lower_arm':lo,'wrist_rula':wr,'neck_rula':n,'trunk_rula':t,
                          'legs':legs,'muscle':muscle,'load_rula':load_rula,'load_reba':load_reba,'coupling':coupling}}
    rulas = [s['rula'] for s in sides.values() if s.get('rula') is not None]
    rebas = [s['reba'] for s in sides.values() if s.get('reba') is not None]
    observed = sum(1 for j in joints.values() if j['status']=='detected' and (j['confidence'] is None or j['confidence']>=.5))
    return {'algorithm_version':VERSION,'context_revision':context['revision'],
        'status':'preliminary_assumed' if rulas else 'not_evaluable',
        'geometry':'optical_3d_unvalidated' if metric3d else 'projected_2d',
        'rula':max(rulas) if rulas else None,'reba':max(rebas) if rebas else None,
        'sides':sides,'angles':{k:round(v,2) if v is not None else None for k,v in angles.items()},
        'coverage':round(observed/33,4),'observed_joints':observed,'expected_joints':33,
        'assumptions':list(dict.fromkeys(assumptions)), 'phase':phase,
        'context_snapshot':context,
        'observed_at':pose['observed_at'],'frame_id':pose['frame_id']}
