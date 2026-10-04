#!/bin/sh
# Warm panels accept a small D-Bus request instead of importing Python and GTK.
panel=menu
action=show
case "${1:-}" in
  --check-updates) shift; exec "$HOME/.local/bin/abide-update" --check "$@" ;;
  --update) shift; exec "$HOME/.local/bin/abide-update" --apply "$@" ;;
  --doctor) exec "$HOME/.local/bin/abide-doctor" ;;
  --help|-h)
    printf '%s\n' 'Abide — small panels for Xfce' \
      'Usage: abide [--journal | --shortcuts | --toggle | --terminal]' \
      '       abide --check-updates | --update | --doctor' \
      'Super+Space: menu. Super+J: journal. Super+K: shortcuts.'
    exit 0 ;;
esac
for argument in "$@"; do
  case "$argument" in
    --journal|--reflect) panel=journal ;;
    --shortcuts) panel=shortcuts ;;
    --toggle) action=toggle ;;
    *) exec /usr/bin/python3 "$HOME/.local/share/abide/app.py" "$@" ;;
  esac
done
if gdbus call --session --dest local.abide.Panels \
  --object-path /local/abide/Panels --method org.gtk.Actions.Activate \
  "$action" "[<'$panel'>]" '{}' >/dev/null 2>&1; then
  exit 0
fi
# Preserve a working launcher even when the session service is unavailable.
exec /usr/bin/python3 "$HOME/.local/share/abide/app.py" "$@"
