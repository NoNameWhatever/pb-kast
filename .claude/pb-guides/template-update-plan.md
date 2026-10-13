# Mallupdate-plan

En mallupdate som rör kärngolvet är strict, även när den är ren. Planen får vara kort:

- Mallversion före och efter.
- Diffen mot föregående tagg, läst i den monterade mallklonen.
- Identifierade avvikelser, eller att inga fanns.
- Om en `pb-*`-workflow ändras (copier har redan skrivit den i arbetsträdet): pusha först allt utom workflowfilerna, lägg workflowändringen i egen commit och lämna den som patch (rutinen i `pb-workflow.md`). Användaren kör `pb-patch`, som tillämpar den i en ren klon, kontrollerar hela trädet mot taggens hash-manifest ur den verifierade mallklonen och pushar efter hens ja.

Vid konflikt i en mallägd fil: stanna och rapportera. Användaren väljer mallens version och flyttar anpassningen till en skelettfil.
