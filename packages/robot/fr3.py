"""Compose licensed upstream FR3 and Panda hand components for simulation."""
import copy
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


def compose_hand(root,panda):
    root,panda=Path(root),Path(panda)
    arm=ET.parse(root/'fr3.xml').getroot();source=ET.parse(panda/'panda.xml').getroot()
    hand=copy.deepcopy(source.find(".//body[@name='hand']"))
    hand.set('childclass','gripper_panda');hand.set('pos','0 0 0.107')
    classes={d.get('class') for d in source.findall('.//default') if d.get('class')}
    defaults=copy.deepcopy(source.find('default/default'))
    for element in [*defaults.iter(),*hand.iter()]:
        for key in ('class','childclass'):
            value=element.get(key)
            if value in classes:element.set(key,'gripper_'+value)
    arm.find('default').append(defaults)
    meshes={g.get('mesh') for g in hand.iter('geom') if g.get('mesh')}
    materials={g.get('material') for g in hand.iter('geom') if g.get('material')}
    for asset in source.find('asset'):
        name=asset.get('name') or Path(asset.get('file','')).stem
        if (asset.tag=='mesh' and name in meshes) or (asset.tag=='material' and name in materials):
            item=copy.deepcopy(asset);item.set('name','gripper_'+name)
            if item.get('class') in classes:item.set('class','gripper_'+item.get('class'))
            if item.get('file'):
                relative=Path('gripper')/item.get('file');target=root/'assets'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(panda/'assets'/item.get('file'),target);item.set('file',relative.as_posix())
            arm.find('asset').append(item)
    for geom in hand.iter('geom'):
        for key in ('mesh','material'):
            if geom.get(key):geom.set(key,'gripper_'+geom.get(key))
    arm.find(".//body[@name='fr3_link7']").append(hand)
    for name in ('tendon','equality'):arm.append(copy.deepcopy(source.find(name)))
    actuator=copy.deepcopy(source.find("actuator/general[@name='actuator8']"));actuator.set('class','gripper_panda')
    arm.find('actuator').append(actuator)
    arm.remove(arm.find('keyframe'))
    ET.ElementTree(arm).write(root/'fr3_hand.xml',encoding='unicode')
    shutil.copyfile(panda/'LICENSE',root/'PANDA_HAND_LICENSE')
