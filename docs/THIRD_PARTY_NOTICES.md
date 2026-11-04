# Third-party components and assets

Dependencies retain their own licenses. Model access approval does not replace
model/checkpoint or source-media license terms. This notice does not change the
license of this repository or grant rights to third-party data.

| Component | Official source / applicable terms |
| --- | --- |
| Muse / SAM hosted models | [Meta developer platform](https://developers.meta.com/); account and model-specific provider terms apply |
| VGGT | [facebookresearch/vggt](https://github.com/facebookresearch/vggt); retain upstream source and checkpoint licenses |
| SAM 3D Body | [facebookresearch/sam-3d-body](https://github.com/facebookresearch/sam-3d-body) and gated checkpoint agreement; retain MHR/DINO terms for included assets |
| MuJoCo | [google-deepmind/mujoco](https://github.com/google-deepmind/mujoco), Apache-2.0 |
| Panda / FR3 assets | [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie), per-model Apache-2.0 licenses retained in downloaded directories |
| LeRobot | [huggingface/lerobot](https://github.com/huggingface/lerobot), Apache-2.0 |
| RLDS definition | [google-research/rlds](https://github.com/google-research/rlds), Apache-2.0 |
| TensorFlow Datasets | [tensorflow/datasets](https://github.com/tensorflow/datasets), Apache-2.0 |
| Gymnasium | [Farama-Foundation/Gymnasium](https://github.com/Farama-Foundation/Gymnasium), MIT |
| Stable-Baselines3 | [DLR-RM/stable-baselines3](https://github.com/DLR-RM/stable-baselines3), MIT |
| TD3+BC reference | [sfujim/TD3_BC](https://github.com/sfujim/TD3_BC); local baseline algorithm reference, not an accuracy claim |

The FR3 hand attachment is an explicit local modification combining two official
simulation assets. `asset_manifest.json` hashes every supplied file and records
the source revision. `PANDA_HAND_LICENSE` accompanies the hand assets. This
composition has not been physically certified.

FFmpeg, MinIO, PostgreSQL, Redis, Python and Node packages retain their respective
licenses. In particular, the pinned MinIO build has upstream AGPL obligations;
review the deployed upstream license and source availability before redistribution.
Source videos must include their acquisition URL, license/authorization and hash
in provenance. Bulk source footage and gated weights are excluded from Git.
