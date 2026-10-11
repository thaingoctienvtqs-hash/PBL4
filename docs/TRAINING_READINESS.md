# Training Readiness

Generated (UTC): 2026-10-11T05:51:43+00:00

Ready for custom YOLO segmentation training: **false**.
Not ready: need at least 10 reviewed polygons per target class, scene-completeness attestations, reviewed SAFE/NEAR/CONTACT labels, independent source-group splits with minimum counts, no hash leakage, valid provenance and no malformed reviewed annotations. Open Images has no painting/hand masks or artwork-contact labels.

## Public Open Images Pilot

Actual validation JPEGs: 100; source mask instances: `{"Person": 54, "Suit": 3, "Ipod": 7, "Mobile phone": 35, "Girl": 1, "Beer": 1, "Horse": 4, "Dress": 3, "Pen": 22, "Coffee cup": 1, "Human body": 1, "Man": 3, "Bicycle wheel": 3, "Jeans": 2, "Belt": 1, "Camera": 1, "Trousers": 2, "Shorts": 2, "Piano": 2, "Human ear": 1, "Remote control": 1, "Broccoli": 1, "Calculator": 1, "Harpsichord": 2, "Human mouth": 1, "Dog": 1, "Wine": 1, "Dumbbell": 1}`.
Target bbox-only instances: `{"Human hand": 44, "Person": 214, "Mobile phone": 9, "Pen": 6}`.
Painting mask: missing. Human hand mask: missing; boxes only. Person and generic tool masks do not provide artwork-contact event labels.
The public pilot stays in `dataset/public/open_images/`; it is not mixed into custom training splits.

## Custom Annotation Status

Recording sessions: 0; extracted frames: 0; LabelMe tasks: 0; annotation states: `{}`.
Reviewed polygons by class: `{}`; minimum target counts: `{"painting": 0, "person": 0, "hand": 0, "tool": 0}`.
Scene-completeness confirmed: False; reviewed event label counts: `{"CONTACT": 0, "NEAR": 0, "SAFE": 0}`; invalid event files: 0.
Custom split counts: `{"train": 0, "val": 0, "test": 0}`; source groups: 0; duplicate hash groups: 0; split hash leakage: False.
Meaningful evaluation split: False; custom files without provenance: 0.
Training ready: **false**. Not ready: need at least 10 reviewed polygons per target class, scene-completeness attestations, reviewed SAFE/NEAR/CONTACT labels, independent source-group splits with minimum counts, no hash leakage, valid provenance and no malformed reviewed annotations. Open Images has no painting/hand masks or artwork-contact labels.

## Remaining Work

- Record consented, representative museum/gallery webcam sessions, including SAFE and NEAR cases.
- Human-review LabelMe polygons for painting, person, hand, and tool; Open Images does not supply painting or hand masks.
- Manually review SAFE/NEAR/CONTACT intervals; do not infer contact from box overlap.
- Collect independent recording sessions for train, validation, and test; one session must never cross splits.
- Resolve tool taxonomy, annotation completeness policy, and class balance from real recordings.
