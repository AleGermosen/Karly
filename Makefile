# Karly — convenience targets.
#
# Remote targets need KARLY_HOST set, e.g.:
#   export KARLY_HOST=marcus@192.168.8.228

.PHONY: help run test curriculum-lint deploy logs status restart stop

help:
	@echo "Local:"
	@echo "  make run       - run the bot locally (needs .env)"
	@echo "  make test      - run the unit tests"
	@echo "Remote (needs KARLY_HOST):"
	@echo "  make deploy    - push + pull + restart on the OptiPlex"
	@echo "  make logs      - follow the remote service logs"
	@echo "  make status    - show remote service status"
	@echo "  make restart   - restart the remote service"
	@echo "  make stop      - stop the remote service"

run:
	.venv/bin/python -m bot.main

test:
	.venv/bin/python -m unittest discover -s tests -v

curriculum-lint:
	python3 scripts/curriculum_lint.py

curriculum-rehash:
	python3 scripts/curriculum_lint.py --rehash

deploy:
	./deploy/deploy.sh

# Both bots (German: karly, English: karly-english) run off the same
# checkout, so the remote targets below cover both by default rather than
# silently leaving one on stale code / not reporting its state.
KARLY_UNITS := karly karly-english

logs:
	ssh "$(KARLY_HOST)" 'journalctl --user -u karly -u karly-english -n 100 -f'

status:
	ssh "$(KARLY_HOST)" 'for u in $(KARLY_UNITS); do echo "== $$u =="; systemctl --user --no-pager status $$u; done'

restart:
	ssh "$(KARLY_HOST)" 'for u in $(KARLY_UNITS); do systemctl --user restart $$u; done'

stop:
	ssh "$(KARLY_HOST)" 'for u in $(KARLY_UNITS); do systemctl --user stop $$u; done'
