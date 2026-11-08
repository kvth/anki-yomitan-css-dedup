**note_types**: names of the Yomitan note types to process. Default `["Yomitan"]`.

**backup_before_apply**: create an Anki backup before writing. Default `true`.

**tag_changed_notes**: when applying, tag the notes that look different with
`yomitan-css-dedup::changed` (after a visual comparison) or all notes the render check
lists with `yomitan-css-dedup::check` (without one). Default `true`.

These settings are easier to change in **Tools → Yomitan CSS Dedup → Settings…**.
