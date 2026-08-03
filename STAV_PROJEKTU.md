# Stav projektu — EngLearning v2

Produkčný repozitár: `kotlas6667/English_learning_with_AI_v2`.

## Hotové

- Shell: Domov, Cvičenie, Pokrok, Profil + bottom nav
- Scenáre, denný cieľ, skill skóre, recap
- Feedback tagy: said / better / tip / score / unclear
- STT: bez dopĺňania kontextu; zopakovanie pri neistote; 2× fail → progres
- PWA (manifest + service worker)
- Mic toggle, settings.json, štatistiky, abandon lekcie

## Deploy

`scripts/haos-full-deploy.sh` **nahrádza v1**: kontajner `englearning`, port `8080`,
cesta `/share/English_learning_with_AI`, dáta vo starom volume.
