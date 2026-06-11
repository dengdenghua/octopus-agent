# Local Agent Skills

Project-owned skill packages live here. Do not depend on `.trae/skills`
at runtime because external tool folders may be deleted or regenerated.

The runtime copies that must be callable by code/admin mode are mirrored
under `runtime/execution/all_skills/` and registered through
`runtime/execution/suckers/agent_doc_skills.py`.
