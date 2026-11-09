# 3D asset inventory (experimental)

This is a **metadata-only** importer. It does not load meshes, run Blender,
download assets, grant likeness authority, or approve production use.

## Usage

Create a local directory containing the asset files and a provenance JSON map
whose keys are relative paths (using forward slashes):

```json
{
  "character.glb": {
    "license": "CC-BY-4.0",
    "url": "https://example.org/original-asset",
    "rights_verified": true,
    "author": "Original creator",
    "attribution": "Character by Original creator, CC BY 4.0",
    "depicts_human": true,
    "depicts_real_person": false,
    "adult_only_attested": true,
    "age_statement": "Source documentation confirms the fictional character is an adult",
    "third_party_character": false
  }
}
```

Only CC0-1.0, CC-BY-4.0 and CC-BY-SA-4.0 are currently
recognized, and only when independently verified. An asset appearing on a
community site does **not** establish ownership or a license. Never assume
an adult-content category establishes a character's age or rights.

```powershell
python -m tools.asset3d_inventory C:\assets\staging C:\assets\provenance.json --output C:\assets\manifest.json
python -m unittest discover -s tests -p test_asset3d_inventory.py -v
```

The output includes SHA-256, duplicate flags, dependency hashes, licensing
metadata, and `likeness_authority: false`. This manifest must never be
accepted as identity evidence by BodyPrint, .mrbody or Photoreal.

**Security boundary:** This is an initial static preflight, not a full
dependency parser for every supported format. In particular, FBX, BLEND and
GLB internal references are not yet exhaustively inspected. OBJ/MTL
advanced texture syntax is rejected; glTF external buffers/images are
checked and hashed. Do not pass untrusted assets to a Blender subprocess
until a separate isolated inspector and complete dependency policy are
implemented. Keep source files outside the repository.
