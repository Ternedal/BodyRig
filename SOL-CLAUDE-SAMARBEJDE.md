# BodyRig samarbejdsdisciplin

Denne fil beskriver samarbejdsregler for parallelle agenter/assistenter på BodyRig. Den er procesautoritet — ikke en påstand om, hvem der har skrevet bestemte commits.

## Før arbejde starter

1. Læs `HANDOFF.md`.
2. Bekræft den aktuelle `main` SHA og om trunk-normalisering er i gang.
3. Brug `main` som base for nyt arbejde, medmindre en eksplicit fysisk/frozen evidence-procedure kræver en anden exact base.
4. Kontrollér åbne PR'er for overlap før en ny branch oprettes.
5. Start ikke et nyt parallelt spor for et problem, der allerede har en aktiv PR, uden at dokumentere hvorfor.

## Branch-regel

Efter foundation-landingen er normalformen:

```text
main
  └─ én kort feature/fix-branch
       └─ PR tilbage til main
```

Undgå kæder af feature-branches oven på feature-branches. Stacking må kun bruges, når en senere ændring reelt afhænger af en endnu ikke-landet ændring, og det skal stå eksplicit i både PR'en og `HANDOFF.md`.

## PR-kontrakt

En BodyRig-PR skal som minimum indeholde:

- formål;
- exact base SHA;
- exact valideret head SHA;
- ændrede authority/trust-boundaries;
- hvad PR'en **ikke** gør;
- CI/test-resultater;
- fysisk validering der stadig mangler;
- `production_activation`-konsekvens;
- stacking/supersession-relation til andre PR'er.

CI-grøn betyder softwaregrøn. Det betyder ikke fysisk godkendt, visuelt godkendt eller produktionsklar.

## Fysisk evidence og freeze

Eksisterende fysisk evidence er bundet til den revision, som evidencen selv angiver. En rebase, merge eller trunk-oprydning omskriver aldrig historisk fysisk authority.

Når en procedure kræver en frozen exact SHA:

- flyt ikke den branch/head under kørslen;
- land ikke sideændringer ind i den;
- brug separate helper/integration branches hvis nødvendigt;
- dokumentér restore-/continuation-pathen;
- behold `production_activation=false`, indtil den eksplicitte final gate siger andet.

## Når en PR bliver overhalet

En gammel PR må ikke bare lukkes, fordi en nyere ser større ud. Klassificér den først som én af:

- `LANDED` — alt relevant indhold findes på trunk; angiv commit/PR.
- `SUPERSEDED` — en anden PR erstatter funktionen; angiv hvilken og hvorfor.
- `FROZEN EVIDENCE` — beholdes som historisk/fysisk reference, ikke aktiv integration.
- `ACTIVE` — har stadig unik kode eller authority, som ikke er landet.

Hvis en PR har unik kode, skal den kode enten bevidst kasseres med begrundelse eller flyttes til den aktive linje før lukning.

## Handoff mellem agenter

Når arbejdet stoppes eller overdrages, opdatér `HANDOFF.md` med:

- branch/PR;
- exact head SHA;
- hvad der konkret blev færdigt;
- hvad der stadig blokerer;
- seneste validering;
- næste sikre handling;
- ting der **ikke** må merges/aktiveres endnu.

Undgå handoffs som kun siger "fortsæt herfra". En anden agent skal kunne afgøre næste skridt uden at rekonstruere hele git-grafen.

## Konfliktregel

Hvis to aktive spor ændrer samme authority-, package-, runtime-, recovery- eller physical-gate-kode, stop parallel landing og sammenlign dem mod trunk først. Duplikeret patch-indhold skal deduplikeres; forskellig authority-semantik skal løses eksplicit før landing.

## Permanent mål

BodyRig skal kunne forstås ud fra:

1. `main`;
2. `HANDOFF.md`;
3. åbne PR'er;
4. fysisk evidence bundet til exact SHAs.

Ingen behøver kende en 50+ branch historik for at vide, hvad der gælder.
