"""Pure game rules; no Telegram calls. All choices resolved from one snapshot."""
import collections
import random

ROLES = {
 'mafia': '⚔️ Рейдер — +10 к атаке',
 'doctor': '💊 Медик — припасы лечат на 25 HP',
 'detective': '🔎 Разведчик — припасы раскрывают случайную роль',
 'armor': '🛡 Броненосец — поглощает 10 урона от атак за ночь',
 'sniper': '🎯 Снайпер — один выстрел на 45, игнорирует защиту',
 'assassin': '🗡 Ассасин — +15 урона ищущим припасы',
 'trapper': '🪤 Ловчий — при защите ловушка наносит 15 первому нападающему',
 'thief': '🦹 Вор — дважды крадёт до 10 усиления вместо хода',
 'poisoner': '☠️ Отравитель — один яд: 10 HP в течение трёх следующих ночей',
 'alchemist': '🧪 Алхимик — один эликсир восстанавливает 40 HP вместо хода',
 'berserker': '🪓 Берсерк — при HP ≤40 в начале ночи +15 к атаке',
 'engineer': '🧱 Инженер — два укрытия, блокирующих до 40 урона вместо хода',
 'ghost': '👤 Призрак — один раз скрывается от атак вместо хода',
 'vampire': '🩸 Вампир — лечится на треть реально нанесённого атакой урона',
 'impostor': '🎭 Самозванец — разведка показывает другую роль',
 'agitator': '📢 Агитатор — раз за игру удваивает свой голос до начала голосования',
 'immune': '⚖️ Неприкосновенный — один раз блокирует ночной урон от текущего яда',
 'hunter': '🐺 Охотник — гибель тайной цели даёт постоянные +10 к атаке',
 'mutant': '🧬 Мутант — в начале ночи восстанавливает 5 HP',
 'avenger': '🔥 Мститель — погибнув от атак, наносит одному нападавшему 25 урона',
}
SPECIAL = {'sniper':('shot',1), 'thief':('steal',2), 'poisoner':('poison',1),
           'alchemist':('elixir',1), 'engineer':('shelter',2), 'ghost':('hide',1)}
LABELS = {'shot':'🎯 Выстрел', 'steal':'🦹 Кража', 'poison':'☠️ Яд', 'elixir':'🧪 Эликсир', 'shelter':'🧱 Укрытие', 'hide':'👤 Скрыться'}
TARGETED = {'shot','steal','poison','attack'}
RNG = random.SystemRandom()


def setup(players):
    roles = RNG.sample(list(ROLES), len(players))
    for p, role in zip(players.values(), roles):
        p.update(role=role, hp=100, alive=True, power=0, used=0, poison=[], boosted=False,
                 boost_used=False, immunity_used=False, abstain_used=False, bounty=False)
    for uid,p in players.items():
        if p['role']=='hunter':
            p['prey']=RNG.choice([u for u in players if u!=uid])


def defaults(p):
    if p['role']=='citizen': p['role']='armor'
    for k,v in {'hp':100,'power':0,'used':0,'poison':[],'boosted':False,'boost_used':False,'immunity_used':False,'abstain_used':False,'bounty':False}.items():
        if k not in p: p[k]=v.copy() if isinstance(v,list) else v


def parse_action(value):
    if value in ('guard','loot','elixir','shelter','hide'): return value,None
    if '~' in value: return tuple(value.split('~',1))
    return 'attack', value


def valid_action(players, uid, value):
    p=players.get(uid)
    if not p or not p['alive']: return False
    kind,target=parse_action(value)
    if kind in TARGETED and (target==uid or target not in players or not players[target]['alive']): return False
    if kind in ('guard','loot','attack'): return True
    ability = SPECIAL.get(p['role'])
    return bool(ability and kind==ability[0] and p.get('used',0)<ability[1])


def vote_counts(g):
    ps = g['players']
    counts = collections.Counter()
    for uid, target in g['votes'].items():
        p = ps.get(uid)
        if p and p['alive'] and (target == '0' and not p.get('abstain_used') or target in ps and ps[target]['alive'] and target != uid):
            counts[target] += 2 if p.get('boosted') else 1
    return counts


def council(g):
    ps = g['players']
    counts = vote_counts(g)
    counts.pop('0', None)  # Abstentions are shown but are not a candidate.
    for uid, p in ps.items():
        if p['alive'] and g['votes'].get(uid) == '0' and not p.get('abstain_used'):
            p['abstain_used'] = True
        p['boosted'] = False
    ranks = counts.most_common()
    if not ranks or len(ranks) > 1 and ranks[0][1] == ranks[1][1]:
        return None, 0
    target = ranks[0][0]
    damage = ps[target]['hp']
    ps[target].update(hp=0, alive=False)
    bounties(ps)
    return target, damage


def bounties(ps):
    for p in ps.values():
        prey=ps.get(p.get('prey'))
        if p['role']=='hunter' and prey and not prey['alive']: p['bounty']=True


def resolve_night(g, rng=None):
    rng=rng or RNG
    ps=g['players'];alive={u:p for u,p in ps.items() if p['alive']}
    for p in alive.values(): defaults(p)
    actions={u:parse_action(g['votes'].get(u,'guard')) if valid_action(ps,u,g['votes'].get(u,'guard')) else ('guard',None) for u in alive}
    start_hp={u:p['hp'] for u,p in alive.items()}
    start_power={u:p['power'] for u,p in alive.items()}
    notes=[];attacks=[];trap_damage=collections.Counter();poison_damage={};pending=[]
    # Old poison ticks now; newly applied poison starts next night.
    for u,p in alive.items():
        poison_damage[u]=10*len(p['poison'])
        if poison_damage[u] and p['role']=='immune' and not p.get('immunity_used'):
            poison_damage[u]=0
            p['immunity_used']=True
        p['poison']=[n-1 for n in p['poison'] if n>1]
    for u,p in alive.items():
        kind,target=actions[u]
        if kind not in ('attack','guard','loot'): p['used']+=1
        if kind=='loot':
            p['hp']=min(100,p['hp']+(25 if p['role']=='doctor' else 15))
            p['power']=min(20,p['power']+5)
            if p['role']=='detective':
                t=rng.choice([v for v in alive if v!=u]);role=ps[t]['role']
                if role=='impostor': role=rng.choice([r for r in ROLES if r!='impostor'])
                notes.append((u,'🔎 Разведка: '+ps[t]['name']+' — '+ROLES[role]))
        elif kind=='elixir': p['hp']=min(100,p['hp']+40)
        elif kind=='steal':
            amount=min(10,start_power[target]);pending.append((u,target,amount))
        elif kind=='poison': ps[target]['poison'].append(3)
        elif kind in ('attack','shot'):
            dmg=45 if kind=='shot' else 25+start_power[u]+(10 if p['role']=='mafia' else 0)+(15 if p['role']=='berserker' and start_hp[u]<=40 else 0)+(10 if p.get('bounty') else 0)
            if kind=='attack' and p['role']=='assassin' and actions[target][0]=='loot': dmg+=15
            attacks.append((u,target,dmg,kind=='shot'))
    # Theft cannot erase a simultaneous loot gain; attacks use pre-night power.
    for u,t,amount in pending:
        ps[t]['power']=max(0,ps[t]['power']-amount)
        ps[u]['power']=min(20,ps[u]['power']+amount)
        notes.append((u,f'🦹 Украдено усиление: {amount}.'))
    credits=collections.Counter();actual_damage={};attackers={}
    for t,p in alive.items():
        incoming=[a for a in attacks if a[1]==t]
        attackers[t]=[a[0] for a in incoming]
        normal=sum(a[2] for a in incoming if not a[3]);piercing=sum(a[2] for a in incoming if a[3])
        kind=actions[t][0]
        if kind=='hide': normal=piercing=0
        elif kind=='guard': normal=(normal+1)//2
        if kind=='shelter': normal=max(0,normal-40)
        if p['role']=='armor': normal=max(0,normal-10)
        actual_damage[t]=normal+piercing
        # Attribute effective damage proportionally; sorted IDs resolve rounding.
        effective=min(p['hp'],actual_damage[t]);total=sum(a[2] for a in incoming)
        if total and effective:
            shares={a[0]:effective*a[2]//total for a in incoming}
            remainder=effective-sum(shares.values())
            for a in sorted(incoming)[:remainder]: shares[a[0]]+=1
            for source,dmg in shares.items(): credits[source]+=dmg
        if p['role']=='trapper' and kind=='guard' and incoming:
            trap_damage[sorted(incoming)[0][0]]+=15
    # Vampires heal before simultaneous damage; attack deaths trigger revenge,
    # poison/arena/traps alone do not. Revenge does not cascade.
    hazard=min(100,max(0,g['round']-2)*10)
    revenge=collections.Counter()
    for u,p in alive.items():
        if p['role']=='vampire': p['hp']=min(100,p['hp']+credits[u]//3)
        before=p['hp'];hit=actual_damage[u]
        if p['role']=='avenger' and hit>=before and attackers[u]:
            revenge[rng.choice(attackers[u])]+=25
        p['hp']=max(0,before-hit-trap_damage[u]-poison_damage[u]-hazard)
    for u,damage in revenge.items(): ps[u]['hp']=max(0,ps[u]['hp']-damage)
    for p in alive.values(): p['alive']=p['hp']>0
    bounties(ps)
    return hazard,notes
