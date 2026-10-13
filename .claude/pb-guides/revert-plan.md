# Revert-plan

En revert av en strict-ändring går genom vanlig process, utan snabbväg. Planen anger:

- PR och SHA som revertas, och skälet.
- Vad reverten inte återställer: data skriven under den nya vägen, destruktiva migrationer, redan utlösta externa effekter.
- Att schemat är kompatibelt med koden efter reverten.
- Patchsteget, om PR:en ändrade workflows.

Produktionen backas inte via git utan genom att föregående artefakt deployas om (användarens steg). Efter en rollback deployas inget från main förrän reverten är mergad. En down-migration räknas aldrig som rollback-plan.
