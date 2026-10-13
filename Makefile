# Skelett (D3:13). De fem målen är kontrakt (D5:5) och delegerar till mallens dispatcher;
# lägg projektets egna mål nedanför. CI anropar aldrig `make` (D5:4).
.PHONY: test lint run check fmt

test:
	@.claude/pb-bin/pb-gate test

lint:
	@.claude/pb-bin/pb-gate lint

run:
	@.claude/pb-bin/pb-gate run

# Det CI kör, plus den lokala secret scan (D6:26).
check:
	@.claude/pb-bin/pb-gate check

# Formaterar filer som ändrats mot main. Uttryckliga filer: make fmt FILES="a.py b.py"
fmt:
	@.claude/pb-bin/pb-gate fmt $(FILES)
