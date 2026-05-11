# Google Web 10 Curated Bundle

This bundle is the first real public-archive Cyber-Bench bundle. It uses Google
CTF web challenges downloaded into `resources/ctf-archives/google-ctf`.

The manifest intentionally stores provenance for every scored service:

- `source_id`
- `source_path`
- `upstream_license`
- `build_context`

The upstream Google CTF challenge YAML files reference prebuilt Artifact
Registry images, but those images are not anonymously pullable. This bundle
builds local images from the public checked-in challenge Dockerfiles instead.
Some services run privileged because the upstream kCTF Dockerfiles expect that
runtime shape.

Flags are the public original flags from the challenge metadata/YAML for this
first runnable curation pass. Later imports should normalize flags to
`CYBERBENCH{...}` when the challenge can be safely rewritten.

This bundle has exactly 10 scored web CTF services and 3 benign decoy services.
