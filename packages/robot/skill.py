"""Infer what was done to an object from a demonstration, not where the hand was.

The hand path while in contact is fitted with three candidate constraints: none
(static), a line (prismatic joint) and an arc (revolute joint). The winner plus
scale-free descriptors (swept angle, pull-versus-push, order and timing of phases)
form a skill that can be re-instantiated on a different scene.
Everything here is an estimate from relative-scale geometry; residuals are kept.
"""
import numpy as np

from packages.common.utils import DomainError
from packages.schemas.replication import MotionFit, SkillModel, SkillPhase, TransportSkill

STATIC_RATIO = .15  # object motion below this share of the whole hand excursion is "no motion"
STATIC_SPREAD = .1  # contact-phase RMS spread below this share of the whole hand excursion is a resting hand
LINE_LIMIT = .12
ARC_LIMIT = .08
# Real monocular depth is noisier than these limits allow. When the object's name
# already says what kind of joint it has, a looser fit of that joint is accepted.
LINE_LIMIT_NAMED = .2
ARC_LIMIT_NAMED = .16
# A circle always fits noise a little better than a line. It is a clear hinge only
# when the line leaves this many times the residual and loses by this BIC margin.
# Between "clear line" and "clear hinge" the object's name breaks the tie.
# A named hinge is not weighed against a line at all: a lid cannot slide.
ARC_RATIO, ARC_MARGIN, ARC_HINT, ARC_UNAIDED = 2., 6., -np.inf, 4.
# Hinged things by how their hinge lies: a lid's is level, a door's is upright.
LIDS = ("LAPTOP", "LID", "FLAP", "COVER", "OVEN", "BOOK", "HATCH", "TOILET", "TRUNK", "CHEST")
DOORS = ("DOOR", "GATE", "FRIDGE", "MICROWAVE", "WINDOW", "CUPBOARD")
HINGED = LIDS+DOORS+("HINGE",)
SLIDING = ("DRAWER", "SLIDE", "SLIDING", "TRAY", "RAIL")
PRESSABLE = ("BUTTON", "SWITCH", "KEY", "DOORBELL")
TWISTABLE = ("KNOB", "DIAL", "VALVE", "FAUCET", "TAP", "CAP", "JAR")
CARRY_WORDS, PRESS_WORDS, TWIST_WORDS = ("LIFT", "TRANSPORT", "PLACE"), ("PRESS",), ("ROTATE",)
OPEN_WORDS, CLOSE_WORDS = ("OPEN", "PULL", "LIFT"), ("CLOSE", "PUSH")


def unit(vector):
    norm = float(np.linalg.norm(vector))
    return np.asarray(vector, float)/norm if norm > 1e-12 else None


def extent(points):
    points = np.asarray(points, float)
    return float(np.max(np.linalg.norm(points[:, None]-points[None], axis=2))) if len(points) > 1 else 0.


def steadied(points):
    """Median of each sample and its neighbors. Removes single-frame depth spikes, keeps the path."""
    points = np.asarray(points, float)
    if len(points) < 5:
        return points
    padded = np.vstack([points[:1], points, points[-1:]])
    return np.median(np.stack([padded[:-2], padded[1:-1], padded[2:]]), axis=0)


def bic(rss, n, parameters, floor):
    return float(n*np.log(max(rss, floor)/n)+parameters*np.log(n))


def fit_line(points):
    center = points.mean(0)
    _, _, vt = np.linalg.svd(points-center)
    direction = vt[0]
    if np.dot(points[-1]-points[0], direction) < 0:
        direction = -direction
    along = (points-center) @ direction
    residual = points-center-np.outer(along, direction)
    return {"direction": direction, "center": center, "along": along, "rss": float((residual**2).sum())}


def circle_in_plane(points, center, u, v):
    """Circle through points projected on the plane (u, v); residual includes distance off the plane."""
    normal = np.cross(u, v)
    xy = np.column_stack([(points-center) @ u, (points-center) @ v])
    out_of_plane = (points-center) @ normal
    system = np.column_stack([2*xy, np.ones(len(xy))])
    solution, *_ = np.linalg.lstsq(system, (xy**2).sum(1), rcond=None)
    refined = np.r_[solution[:2], np.sqrt(max(solution[2]+solution[:2] @ solution[:2], 1e-12))]
    error = lambda c: np.linalg.norm(xy-c[:2], axis=1)-c[2]
    for _ in range(30):
        # Gauss-Newton on radial distance error; keep a step only if it lowers the error.
        offset = xy-refined[:2]
        distance = np.maximum(np.linalg.norm(offset, axis=1), 1e-12)
        residual = distance-refined[2]
        jacobian = np.column_stack([-offset/distance[:, None], -np.ones(len(xy))])
        step, *_ = np.linalg.lstsq(jacobian, -residual, rcond=None)
        if error(refined+step) @ error(refined+step) >= residual @ residual:
            break
        refined = refined+step
        if np.linalg.norm(step) < 1e-10*max(abs(refined[2]), 1e-12):
            break
    angles = np.unwrap(np.arctan2(xy[:, 1]-refined[1], xy[:, 0]-refined[0]))
    if angles[-1] < angles[0]:
        normal, angles = -normal, -angles
    return {"origin": center+refined[0]*u+refined[1]*v, "axis": normal, "radius": float(abs(refined[2])),
            "angles": angles-angles[0], "rss": float((error(refined)**2).sum()+(out_of_plane**2).sum())}


def fit_arc(points, up=None, hinge=None):
    """Best circle through the points. NumPy only: this runs in the API image, which has no SciPy.

    Unconstrained, the plane is the points' own (PCA). When the object's name says how
    its hinge lies, the axis is held to that: upright for a door, level for a lid. A
    level axis still has one free heading, which is searched; this keeps the noisiest
    direction of a monocular reconstruction from tilting the fitted plane.
    """
    center = points.mean(0)
    if hinge == "door" and up is not None:
        level = (points-center)-np.outer((points-center) @ up, up)
        u = np.linalg.svd(level)[2][0]
        return circle_in_plane(points, center, u, np.cross(up, u))
    if hinge == "lid" and up is not None:
        first = unit(np.cross(up, [1., 0, 0])) if abs(up[0]) < .9 else unit(np.cross(up, [0, 1., 0]))
        second = np.cross(up, first)
        candidates = []
        for heading in np.linspace(0, np.pi, 36, endpoint=False):
            axis = np.cos(heading)*first+np.sin(heading)*second
            candidates.append(circle_in_plane(points, center, np.cross(up, axis), up))
        return min(candidates, key=lambda fit: fit["rss"])
    _, _, vt = np.linalg.svd(points-center)
    # Right-handed basis: a counter-clockwise angle in (u, v) is a rotation about +normal.
    return circle_in_plane(points, center, vt[0], vt[1])


def monotone(values, total):
    if abs(total) < 1e-12:
        return [0.]*len(values)
    return np.clip(np.maximum.accumulate(np.asarray(values)/total), 0, 1).tolist()


def described(itr, config, plan, start, end):
    """Primitives the semantic plan gives this hand (and this object) in a time window.

    The reconstruction keeps only primitive and timing. With the semantic plan the
    actions are filtered to the selected hand, so one hand's hold is not read as
    the other hand's press.
    """
    words = set()
    if plan is not None:
        for action in plan["actions"]:
            if action.get("actor") not in (None, config.hand_id) or action.get("object") not in (None, config.object_id):
                continue
            if action["end_s"] >= start and action["start_s"] <= end:
                words.add(str(action["primitive"]).upper())
        return words
    for action in getattr(itr, "refined_actions", None) or []:
        a = action.refined_start_s if action.refined_start_s is not None else action.semantic_start_s
        b = action.refined_end_s if action.refined_end_s is not None else action.semantic_end_s
        if b >= start and a <= end:
            words.add(str(getattr(action.primitive, "value", action.primitive)).upper())
    return words


def semantic_hint(itr, config, plan=None, window=None):
    """OPEN/CLOSE style evidence from the semantic plan. Advisory only."""
    words = described(itr, config, plan, *(window or (config.start_s, config.end_s)))
    opens, closes = any(w in OPEN_WORDS for w in words), any(w in CLOSE_WORDS for w in words)
    if not opens and not closes:
        # Free text is a last resort: "close an open laptop" contains both words.
        text = f"{getattr(itr, 'canonical_skill', '')}".upper() or f"{getattr(itr, 'task', '')}".upper()
        opens, closes = "OPEN" in text, "CLOS" in text or "SHUT" in text
    return "open" if opens and not closes else "close" if closes and not opens else None


def joint_prior(itr, config):
    """Expected joint type from the manipulated object's semantic name. Advisory."""
    names = [f"{e.semantic_name} {e.category}" for e in getattr(itr, "entities", None) or [] if e.entity_id == config.object_id]
    text = " ".join(names).upper()
    hinged, sliding = any(w in text for w in HINGED), any(w in text for w in SLIDING)
    return ("revolute", text.strip().lower()) if hinged and not sliding else ("prismatic", text.strip().lower()) if sliding and not hinged else (None, None)


def hinge_prior(named):
    """'lid' or 'door' when the object's name says how its hinge lies."""
    text = (named or "").upper()
    lid, door = any(w in text for w in LIDS), any(w in text for w in DOORS)
    return "lid" if lid and not door else "door" if door and not lid else None


def action_prior(itr, config, start, end, named, plan=None):
    """What kind of action the semantic plan and the object's name describe. Advisory."""
    words = described(itr, config, plan, start, end)
    text = (named or "").upper()
    return {"carry": bool(words & set(CARRY_WORDS)), "press": bool(words & set(PRESS_WORDS)) or any(w in text for w in PRESSABLE),
            "twist": bool(words & set(TWIST_WORDS)) or any(w in text for w in TWISTABLE)}


def object_name(itr, config):
    return " ".join(f"{e.semantic_name} {e.category}" for e in getattr(itr, "entities", None) or [] if e.entity_id == config.object_id).strip().lower()


def planned_window(plan, config, hand_rows):
    """When the plan says this hand manipulated this object, clipped to the sampled hand poses."""
    if plan is None:
        return None
    acts = [a for a in plan["actions"] if a.get("actor") == config.hand_id and a.get("object") == config.object_id
            and a["primitive"] not in ("REACH", "RELEASE", "UNKNOWN")]
    if not acts:
        return None
    start, end = min(a["start_s"] for a in acts), max(a["end_s"] for a in acts)
    inside = [r["t"] for r in hand_rows if start <= r["t"] <= end]
    return (inside[0], inside[-1]) if len(inside) >= 4 else None


def extract_skill(itr, config, plan=None):
    selected = sorted((f for f in itr.frames if f.shot_id == config.shot_id and config.start_s <= f.timestamp <= config.end_s),
                      key=lambda f: f.timestamp)
    if not selected:
        raise DomainError("E_ROBOT_INTERVAL", "No frames in selected shot/interval")
    if len({f.world_frame for f in selected}) != 1:
        raise DomainError("E_ROBOT_FRAME", "Cannot infer a skill across different world frames")
    rows = []
    for frame in selected:
        hands = [p for p in frame.hands if p.entity_id == config.hand_id and p.pose is not None]
        objects = [p for p in frame.objects if p.entity_id == config.object_id and p.pose is not None]
        contacts = [c for c in frame.contacts if c.hand_id == config.hand_id and c.object_id == config.object_id]
        rows.append({"t": frame.timestamp, "hand": np.array(hands[0].pose.position_xyz) if len(hands) == 1 else None,
                     "object": np.array(objects[0].pose.position_xyz) if len(objects) == 1 else None,
                     "contact": len(contacts) == 1 and contacts[0].state == "CONTACT"})
    hand_rows = [r for r in rows if r["hand"] is not None]
    if len(hand_rows) < 4:
        raise DomainError("E_SKILL_GEOMETRY", "Need at least four hand pose samples to infer a skill; reconstruct a denser interval", 409)
    reasons = ["Skill is inferred from relative-scale hand geometry; the source object's joint was not measured"]
    contact_rows = [r for r in hand_rows if r["contact"]]
    whole = np.array([r["hand"] for r in hand_rows])
    planned = planned_window(plan, config, hand_rows)
    if len(contact_rows) >= 3:
        engage, release = contact_rows[0]["t"], contact_rows[-1]["t"]
        moving, source = [r for r in hand_rows if engage <= r["t"] <= release], "hand_during_contact"
    elif planned:
        # No contact evidence (typically the object was not matched to a track). The plan
        # still says when this hand acted on this object; the reach is left out.
        engage, release = planned
        moving, source = [r for r in hand_rows if engage <= r["t"] <= release], "hand_during_planned_action"
        reasons.append("No usable contact evidence; the semantic plan's action interval defines the manipulation")
    else:
        # Without contact evidence the object's own motion marks the manipulation.
        object_rows = [r for r in rows if r["object"] is not None]
        moved = extent([r["object"] for r in object_rows]) if len(object_rows) >= 4 else 0.
        if moved > STATIC_RATIO*extent(whole) and len(object_rows) >= 4:
            moving, source = object_rows, "object"
            reasons.append("No usable contact evidence; the object's own motion defines the manipulation")
        else:
            moving, source = hand_rows, "hand_whole_interval"
            reasons.append("No usable contact evidence; the whole interval is treated as manipulation")
        engage, release = moving[0]["t"], moving[-1]["t"]
    others = sorted({a.get("actor") for a in (plan or {}).get("actions", []) if a.get("object") == config.object_id
                     and a.get("actor") not in (None, config.hand_id) and a["primitive"] not in ("REACH", "PRESS", "UNKNOWN")
                     and a["end_s"] >= engage and a["start_s"] <= release})
    if others:
        reasons.append(f"Another hand ({', '.join(others)}) acts on this object at the same time; only the selected hand's part is replicated")
    key = "object" if source == "object" else "hand"
    points, times = steadied([r[key] for r in moving]), [r["t"] for r in moving]
    n, size, reference = len(points), extent(points), max(extent(whole), 1e-9)
    floor = n*(2e-3*max(size, 1e-9))**2
    up = unit(config.replication.up_hint_world)
    prior, named = joint_prior(itr, config)
    lies = hinge_prior(named) if prior == "revolute" else None
    line, arc = fit_line(points), fit_arc(points, up, lies) if n >= 5 else None
    static_rss = float(((points-points.mean(0))**2).sum())
    relative = lambda rss: float(np.sqrt(rss/n)/max(size, 1e-9))
    fits = [MotionFit(kind="static", relative_rmse=relative(static_rss), bic=bic(static_rss, n, 3, floor), parameters=3),
            MotionFit(kind="prismatic", relative_rmse=relative(line["rss"]), bic=bic(line["rss"], n, 5, floor), parameters=5)]
    if arc:
        fits.append(MotionFit(kind="revolute", relative_rmse=relative(arc["rss"]), bic=bic(arc["rss"], n, 6, floor), parameters=6))
    before = [r["hand"] for r in hand_rows if r["t"] <= engage+1e-9]
    approach = unit(before[-1]-before[0]) if len(before) >= 2 and np.linalg.norm(before[-1]-before[0]) > .05*reference else None
    result = {"kind": "unconstrained", "template": "none", "direction": "unknown", "direction_evidence": "No supported joint was identified",
              "progress": [0.]*n, "displacement": 0., "displacement_unit": "none", "axis_alignment": "unknown"}
    sweep = float(arc["angles"][-1]) if arc else 0.
    ratio = fits[1].relative_rmse/max(fits[2].relative_rmse, 1e-9) if arc else 1.
    margin = fits[1].bic-fits[2].bic if arc else -np.inf
    arc_limit = ARC_LIMIT_NAMED if prior == "revolute" else ARC_LIMIT
    line_limit = LINE_LIMIT_NAMED if prior == "prismatic" else LINE_LIMIT
    plausible = bool(arc) and sweep >= config.replication.min_angle_rad and fits[2].relative_rmse <= arc_limit and arc["radius"] < 20*size
    clear = plausible and margin >= ARC_MARGIN and ratio >= ARC_RATIO
    hinge = clear or plausible and margin >= (ARC_HINT if prior == "revolute" else np.inf if prior == "prismatic" else ARC_UNAIDED)
    actions = action_prior(itr, config, engage, release, object_name(itr, config), plan)
    # An object with no hinge or slide in its name that the plan says was lifted,
    # carried or placed is a free object, whatever curve its path happens to fit.
    carry = actions["carry"] and prior is None
    object_points = [r["object"] for r in rows if r["object"] is not None and engage <= r["t"] <= release]
    coupled = len(object_points) >= 3 and extent(object_points) >= .5*size
    # Spread about the mean, not the largest gap between two samples: the latter grows
    # with every noisy sample and turns a resting hand into apparent motion.
    spread = float(np.sqrt(static_rss/n))
    if spread < STATIC_SPREAD*reference and source != "hand_whole_interval" or size < 1e-9:
        result.update(kind="static", direction_evidence="The hand barely moved while in contact")
        if actions["press"] and not actions["twist"]:
            result.update(template="button", direction="open", direction_evidence="The hand stayed in place while the plan describes a press")
            reasons.append("A press leaves no measurable hand travel; the press depth is a declared default")
        elif actions["twist"]:
            result.update(template="knob", direction="open", direction_evidence="The hand stayed in place while the plan describes a rotation")
            reasons.append("Hand orientation is not reconstructed; the twist angle and sense are declared defaults")
    elif carry or prior is None and not hinge and fits[1].relative_rmse > line_limit and coupled:
        move = points[-1]-points[0]
        rise = float(move @ up)
        level = move-rise*up
        heights = (points-points[0]) @ up
        heading = None
        if approach is not None:
            reach = approach-(approach @ up)*up
            if np.linalg.norm(reach) > .3 and np.linalg.norm(level) > .1*size:
                heading = float(np.arctan2(up @ np.cross(reach, level), reach @ level))
        released = any(r["t"] > release+1e-9 and not r["contact"] for r in hand_rows) and source == "hand_during_contact"
        steps = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        result.update(kind="transport", template="object", displacement=float(np.linalg.norm(move)), displacement_unit="reconstruction_units",
            progress=monotone(steps, steps[-1]), transport=TransportSkill(horizontal_units=float(np.linalg.norm(level)), rise_units=rise,
                peak_units=float(max(heights.max(), 0)), heading_rad=heading, released=released),
            direction_evidence=("Semantic plan describes lifting or carrying" if carry else "Object moved with the hand along an unconstrained path")
                +f"; the object was {'released' if released else 'still held'} at the end of the interval")
        if not carry:
            reasons.append("Free transport was chosen from geometry alone; the plan does not describe a lift, carry or place")
    elif hinge:
        alignment = abs(float(arc["axis"] @ up))
        vertical = alignment > .8
        if lies:
            reasons.append(f"The hinge was taken as {'upright' if lies == 'door' else 'level'} because the object is named '{named}'")
        tangent = unit(np.cross(arc["axis"], points[0]-arc["origin"]))
        result.update(kind="revolute", axis=arc["axis"], origin=arc["origin"], radius=arc["radius"], displacement=sweep,
            displacement_unit="rad", progress=monotone(arc["angles"], sweep), template="door" if vertical else "lid",
            axis_alignment="vertical" if vertical else "horizontal" if alignment < .5 else "oblique")
        if vertical:
            direction_from_approach(result, approach, tangent)
        else:
            rise = float((points[-1]-points[0]) @ up)
            if abs(rise) > .1*size:
                result.update(direction="open" if rise > 0 else "close", direction_from="up_hint",
                    direction_evidence=f"Handle {'rose' if rise > 0 else 'dropped'} {abs(rise)/size:.0%} of the path extent along the up hint")
            else:
                result["direction_evidence"] = "Handle height change along the up hint is inconclusive"
            if result["axis_alignment"] == "oblique":
                reasons.append("Hinge axis is oblique to the up hint; replicated with a horizontal-hinge lid")
    elif fits[1].relative_rmse <= line_limit and prior != "revolute":
        distance = float(line["along"][-1]-line["along"][0])
        alignment = abs(float(line["direction"] @ up))
        result.update(kind="prismatic", axis=line["direction"], displacement=distance, displacement_unit="reconstruction_units",
            progress=monotone(line["along"]-line["along"][0], distance), template="drawer",
            axis_alignment="vertical" if alignment > .8 else "horizontal" if alignment < .5 else "oblique")
        direction_from_approach(result, approach, line["direction"])
        if alignment > .8:
            reasons.append("Slide axis is vertical in the up hint; replicated with a horizontal drawer")
    elif prior:
        reasons.append(f"The object's name ('{named}') implies a {prior} joint, but the reconstructed hand path does not fit one well enough to measure it")
    else:
        reasons.append("Contact-phase motion fits neither a slide nor a hinge and the object did not move with the hand; use trajectory mode")
    hint = semantic_hint(itr, config, plan, (engage, release))
    if hint and result["direction"] == "unknown" and result["kind"] in ("revolute", "prismatic"):
        result.update(direction=hint, direction_evidence=f"Geometry was inconclusive; semantic plan describes the action as '{hint}'")
    elif hint and result["direction"] not in ("unknown", hint) and result.get("direction_from") == "up_hint":
        # "Up" is assumed to be the camera's up. In a top-down or tilted view that is wrong,
        # while the plan's open/close comes from understanding the whole clip.
        reasons.append(f"The up hint indicated '{result['direction']}' but the semantic plan describes '{hint}'; the plan was used because the camera's up is only assumed to be vertical")
        result.update(direction=hint, direction_evidence=f"Semantic plan describes the action as '{hint}'; the up hint disagreed and was overridden")
    elif hint and result["direction"] not in ("unknown", hint):
        reasons.append(f"Semantic plan suggests '{hint}' but geometry indicates '{result['direction']}'; geometry was kept")
    if result["kind"] in ("revolute", "prismatic") and result["direction"] == "unknown":
        reasons.append("Open/close direction could not be determined; set replication.direction explicitly")
    if n < 8:
        reasons.append(f"Only {n} samples describe the manipulation; joint parameters are weakly constrained")
    chosen = next((f for f in fits if f.kind == result["kind"]), None)
    trust = {"hand_during_contact": 1., "hand_during_planned_action": .8}.get(source, .6)
    limit = arc_limit if result["kind"] == "revolute" else line_limit
    if chosen and chosen.relative_rmse > (ARC_LIMIT if result["kind"] == "revolute" else LINE_LIMIT) and result["kind"] in ("revolute", "prismatic"):
        reasons.append(f"The {result['kind']} fit is loose (relative RMSE {chosen.relative_rmse:.2f}); it was accepted because the object's name implies that joint")
    # Geometry alone is ambiguous when the arc is plausible but not clearly better.
    # The object's name is corroboration; a bare fit margin is not.
    ambiguous = (result["kind"] == "prismatic" and plausible and margin >= 2) or (result["kind"] == "revolute" and not clear)
    clarity = 1. if not ambiguous else .8 if prior == result["kind"] else .4
    if ambiguous:
        decided = f"the object's name ('{named}') decided" if prior == result["kind"] else "the fit margin decided"
        reasons.append(f"A slide and a hinge explain the motion almost equally well; {decided} the joint type")
    confidence = 0. if chosen is None or result["kind"] == "static" else float(np.clip(
        min(1, n/8)*(1-chosen.relative_rmse/limit)*clarity*trust, 0, 1))
    if result["kind"] == "transport":
        # No joint to fit: confidence reflects sampling and whether the plan corroborates.
        confidence = float(min(1, n/8)*(.8 if carry else .4)*trust)
    elif result["template"] in ("button", "knob"):
        confidence = float(min(1, n/8)*.5)
    if prior and result["kind"] in ("revolute", "prismatic") and prior != result["kind"]:
        reasons.append(f"The object's name ('{named}') suggests a {prior} joint but the motion fits a {result['kind']} one")
    if result["kind"] in ("revolute", "prismatic") and confidence < .3:
        reasons.append(f"Low-confidence skill ({confidence:.2f}); verify the joint type and direction before relying on it")
    return SkillModel(hand_id=config.hand_id, object_id=config.object_id, shot_id=config.shot_id, kind=result["kind"],
        transport=result.get("transport"), start_world=points[0].tolist(), end_world=points[-1].tolist(),
        axis_world=None if "axis" not in result else result["axis"].tolist(),
        origin_world=None if "origin" not in result else result["origin"].tolist(), radius_units=result.get("radius"),
        displacement=result["displacement"], displacement_unit=result["displacement_unit"], direction=result["direction"],
        direction_evidence=result["direction_evidence"], axis_alignment=result["axis_alignment"],
        approach_alignment=result.get("approach_alignment"), template=result["template"], progress_times_s=times,
        progress=result["progress"], samples=len(hand_rows), contact_samples=len(contact_rows), motion_source=source,
        phases=[SkillPhase(name="approach", start_s=selected[0].timestamp, end_s=engage, samples=sum(r["t"] < engage for r in hand_rows)),
                SkillPhase(name="manipulate", start_s=engage, end_s=release, samples=n),
                SkillPhase(name="retreat", start_s=release, end_s=selected[-1].timestamp, samples=sum(r["t"] > release for r in hand_rows))],
        fits=fits, confidence=confidence, semantic_hint=hint, review_reasons=reasons)


def direction_from_approach(result, approach, motion):
    """Pulling reverses the reach; pushing continues it. Independent of viewpoint and scale."""
    if approach is None or motion is None:
        result["direction_evidence"] = "No approach motion before contact; pull versus push is undetermined"
        return
    alignment = float(approach @ motion)
    result["approach_alignment"] = alignment
    if alignment < -.2:
        result.update(direction="open", direction_evidence=f"Motion opposes the reach (cosine {alignment:.2f}): a pull")
    elif alignment > .2:
        result.update(direction="close", direction_evidence=f"Motion continues the reach (cosine {alignment:.2f}): a push")
    else:
        result["direction_evidence"] = f"Motion is sideways to the reach (cosine {alignment:.2f}); pull versus push is undetermined"
