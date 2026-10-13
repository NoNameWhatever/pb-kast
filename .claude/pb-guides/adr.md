# ADR (`project-docs/adr/NNNN-slug.md`)

En ADR skrivs när beslutet är svårt att ändra eller någon annars skulle fråga varför (D3:20c). Filen heter `NNNN-slug.md` med nästa fyrsiffriga löpnummer. Du skriver alltid `Status: förslag`: bara användaren ändrar till `beslutad`. Ett ändrat beslut ger en ny ADR med raden `Ersätter: NNNN`, och den gamla får `Status: ersatt av NNNN` utan annan ändring. Utelämna en rubrik aldrig; `Säkerhet och drift` får vara en rad.

## Mall

```
# ADR NNNN: <beslutet i några ord>

## Status
förslag

## Datum
YYYY-MM-DD

## Kontext
Problemet och det som styr, några rader.

## Beslut
Vad som gäller, i presens och utan förbehåll.

## Alternativ
Avfärdade alternativ, en rad skäl vardera. Bara de som någon sannolikt föreslår igen, eller "Inga övervägda".

## Konsekvenser
Vad som blir lättare och svårare, och vad som måste ändras.

## Säkerhet och drift
Det som berörs, eller `Inget berört: <skäl>`.
```

Valfria rader direkt under rubriken: `Ersätter: NNNN` och `Issue: <länk>`.
