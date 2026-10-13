# Hotmodell (`project-docs/threat-model.md`)

Nuläget för ett exponerat projekt, inte historik. En förtroendegräns är där data eller auktoritet byter ägare (webbläsare till server, tjänst till databas, ditt system till en tredjepart). En angreppsyta är det en angripare faktiskt kan nå: route, webhook, port, uppladdning, eller ett beroende som tar extern indata.

## När den ändras
Planen anger under `Security` att hotmodellen ändras, och ändringen ligger i samma PR, när en ändring:
- lägger till eller ändrar en extern ingång (route, webhook, port, kö som tar emot utifrån),
- lägger till eller ändrar autentisering, behörighet, sessioner eller tokens,
- lägger till ett utgående anrop med credentials, eller släpper in data från en ny tredjepart,
- börjar lagra personuppgifter eller credentials,
- tar emot eller bearbetar filer eller annan extern data (uppladdning, import, tolkning),
- ändrar exponeringen (proxy, CORS, öppen port, publik lagring).

## Grundversionen
Är dokumentet tomt när en sådan ändring planeras skriver du hela det exponerade systemets grundversion i samma plan-PR, inte bara ändringen. Användarens merge av PR:en är godkännandet.

## Skrivregler
- Ett hot per punkt, med den angreppsyta det gäller.
- En åtgärd anger sökväg eller beteende. En åtgärd utan det räknas inte.
- Restrisk skriver du som förslag; användaren godkänner genom att mergea.

## Frågelista (STRIDE)
Pröva per förtroendegräns: kan någon utge sig för en annan (spoofing), ändra data på vägen eller i vila (tampering), förneka vad den gjort utan spår (repudiation), läsa det den inte ska (information disclosure), stoppa tjänsten (denial of service), få mer rättigheter än avsett (elevation of privilege)? Listan är något att pröva mot, inget krav per element.
