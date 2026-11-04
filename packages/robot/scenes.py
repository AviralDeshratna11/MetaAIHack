"""One scene builder shared by replay and interactive RL environments."""
import xml.etree.ElementTree as ET
from pathlib import Path


def scene_xml(root, scene=None):
    root = Path(root)
    xml = ET.parse(root/"panda.xml").getroot()
    xml.find("compiler").set("meshdir", str((root/"assets").resolve()))
    world = xml.find("worldbody")
    ET.SubElement(world, "light", pos="0 0 3", dir="0 0 -1", diffuse=".8 .8 .8")
    top = scene.table_top_m if scene else -.01
    ET.SubElement(world, "geom", name="proxy_table", type="plane", size="2 2 .1", pos=f"0 0 {top}", rgba=".35 .4 .35 1")
    ET.SubElement(world, "camera", name="debug", pos="1.6 -1.6 1.2", xyaxes=".707 .707 0 -.3 .3 .9")
    pos = scene.object_position_m if scene else [.5, .22, .04]
    size = scene.object_half_size_m if scene else [.025, .025, .035]
    body = ET.SubElement(world, "body", name="proxy_object", pos=" ".join(map(str, pos)))
    ET.SubElement(body, "freejoint", name="proxy_free")
    ET.SubElement(body, "geom", name="proxy_box", type="box", size=" ".join(map(str,size)),
        mass=str(scene.object_mass_kg if scene else .1),
        friction=f"{scene.friction if scene else .8} .005 .0001", rgba=".8 .4 .2 1")
    if scene:
        ET.SubElement(world, "site", name="task_goal", type="sphere", size=".015", rgba=".2 .8 .2 .4",
                      pos=" ".join(map(str, scene.goal_position_m)))
    keyframe = xml.find("keyframe")
    if keyframe is not None: xml.remove(keyframe)
    return ET.tostring(xml, encoding="unicode")


def forbidden_contacts(model, data, allowed_grasp=False):
    import mujoco as mj
    result = []
    for contact in data.contact[:data.ncon]:
        if contact.dist >= -1e-4: continue
        names = [mj.mj_id2name(model, mj.mjtObj.mjOBJ_GEOM, g) or f"geom:{g}" for g in (contact.geom1,contact.geom2)]
        bodies = [int(model.geom_bodyid[g]) for g in (contact.geom1,contact.geom2)]
        body_names = [mj.mj_id2name(model, mj.mjtObj.mjOBJ_BODY, b) for b in bodies]
        if "proxy_table" in names and any(b in ("link0","proxy_object") for b in body_names): continue
        if allowed_grasp and "proxy_object" in body_names and any(b in ("left_finger","right_finger") for b in body_names): continue
        if bodies[0] == bodies[1] or model.body_parentid[bodies[0]] == bodies[1] or model.body_parentid[bodies[1]] == bodies[0]: continue
        result.append("/".join(names))
    return sorted(set(result))
