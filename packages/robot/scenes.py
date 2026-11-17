"""One scene builder shared by replay and interactive RL environments."""
import xml.etree.ElementTree as ET
from pathlib import Path


def scene_xml(root, scene=None):
    root = Path(root)
    from packages.robot.panda import fingerprint
    xml = ET.parse(root/fingerprint(root)['model_file']).getroot()
    xml.find("compiler").set("meshdir", str((root/"assets").resolve()))
    world = xml.find("worldbody")
    # Presentation only: a lit floor and sky so replays are legible. No physics change.
    visual = ET.SubElement(xml, "visual")
    ET.SubElement(visual, "headlight", ambient=".45 .45 .45", diffuse=".5 .5 .5", specular=".1 .1 .1")
    asset = xml.find("asset")
    ET.SubElement(asset, "texture", type="skybox", builtin="gradient", rgb1=".72 .8 .9", rgb2=".96 .96 .97", width="64", height="384")
    ET.SubElement(asset, "texture", name="proxy_floor", type="2d", builtin="checker", rgb1=".8 .82 .84", rgb2=".72 .74 .77", width="256", height="256")
    ET.SubElement(asset, "material", name="proxy_floor", texture="proxy_floor", texrepeat="8 8", reflectance=".03")
    ET.SubElement(world, "light", pos="0 0 3", dir="0 0 -1", diffuse=".6 .6 .6")
    top = scene.table_top_m if scene else -.01
    ET.SubElement(world, "geom", name="proxy_table", type="plane", size="2 2 .1", pos=f"0 0 {top}", material="proxy_floor")
    if scene and scene.task == "articulated":
        from packages.robot.articulated import Articulation
        # Closer view that keeps the arm and the generated object in frame.
        ET.SubElement(world, "body", name="view_target", pos=".42 0 .3")
        # Each template opens a different way; view it from the side that shows the handle.
        view = {"lid": "1.2 -1.05 .85", "drawer": ".4 -1.5 .8", "door": "-.1 -1.45 .9"}.get(scene.articulation.template, "1.1 -.95 .75")
        ET.SubElement(world, "camera", name="debug", mode="targetbody", target="view_target", pos=view)
        world.append(Articulation(scene.articulation).elements(top))
    else:
        if scene and scene.task == "pick_place":
            # Generated carry tasks sit near the table in front of the robot; view them closer.
            ET.SubElement(world, "body", name="view_target", pos=".45 0 .15")
            ET.SubElement(world, "camera", name="debug", mode="targetbody", target="view_target", pos="1.15 -1. .7")
        else:
            ET.SubElement(world, "camera", name="debug", pos="1.6 -1.6 1.2", xyaxes=".707 .707 0 -.3 .3 .9")
        pos = scene.object_position_m if scene else [.5, .22, .04]
        size = scene.object_half_size_m if scene else [.025, .025, .035]
        body = ET.SubElement(world, "body", name="proxy_object", pos=" ".join(map(str, pos)))
        ET.SubElement(body, "freejoint", name="proxy_free")
        ET.SubElement(body, "geom", name="proxy_box", type="box", size=" ".join(map(str,size)),
            mass=str(scene.object_mass_kg if scene else .1),
            friction=f"{scene.friction if scene else .8} .005 .0001", rgba=".8 .4 .2 1")
        if scene and scene.goal_support_m > 0:
            # Generated support so an object set down above the table has something to rest on.
            height = scene.goal_support_m/2
            ET.SubElement(world, "geom", name="proxy_support", type="box", size=f".06 .06 {height}", rgba=".55 .45 .35 1",
                pos=f"{scene.goal_position_m[0]} {scene.goal_position_m[1]} {top+height}")
    if scene:
        ET.SubElement(world, "site", name="task_goal", type="sphere", size=".015", rgba=".2 .8 .2 .4",
                      pos=" ".join(map(str, scene.goal_position_m)))
    keyframe = xml.find("keyframe")
    if keyframe is not None: xml.remove(keyframe)
    return ET.tostring(xml, encoding="unicode")


def task_joint(model):
    """qpos address of the generated articulation joint, or None for rigid scenes."""
    import mujoco as mj
    joint = mj.mj_name2id(model, mj.mjtObj.mjOBJ_JOINT, "task_joint")
    return None if joint < 0 else int(model.jnt_qposadr[joint])


def reset_task(model, data, scene):
    """Put a generated articulation at its declared start before equilibration."""
    address = task_joint(model)
    if address is not None:
        data.qpos[address] = scene.articulation.start


def object_position(model, data):
    """Handle site for articulated parts (a hinged body origin never moves); body origin otherwise."""
    import mujoco as mj
    site = mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE, "task_handle")
    if site >= 0:
        return data.site_xpos[site].copy()
    return data.xpos[mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, "proxy_object")].copy()


def grasp_allowed(scene):
    return bool(scene and scene.task in ("pick_place", "articulated"))


def forbidden_contacts(model, data, allowed_grasp=False):
    import mujoco as mj
    result = []
    for contact in data.contact[:data.ncon]:
        if contact.dist >= -1e-4: continue
        names = [mj.mj_id2name(model, mj.mjtObj.mjOBJ_GEOM, g) or f"geom:{g}" for g in (contact.geom1,contact.geom2)]
        bodies = [int(model.geom_bodyid[g]) for g in (contact.geom1,contact.geom2)]
        body_names = [mj.mj_id2name(model, mj.mjtObj.mjOBJ_BODY, b) for b in bodies]
        if "proxy_table" in names and any(b in ("link0","fr3_link0","proxy_object") for b in body_names): continue
        if "proxy_support" in names and "proxy_object" in body_names: continue
        if allowed_grasp and "proxy_object" in body_names and any(b in ("left_finger","right_finger") for b in body_names): continue
        if bodies[0] == bodies[1] or model.body_parentid[bodies[0]] == bodies[1] or model.body_parentid[bodies[1]] == bodies[0]: continue
        result.append("/".join(names))
    return sorted(set(result))
