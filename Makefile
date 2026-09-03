# Karly — convenience targets.
#
# Remote targets need KARLY_HOST set, e.g.:
#   export KARLY_HOST=marcus@192.168.8.228

.PHONY: help run test deploy logs status restart stop

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

deploy:
	./deploy/deploy.sh

logs:
	ssh "$(KARLY_HOST)" 'journalctl --user -u karly -n 100 -f'

status:
	ssh "$(KARLY_HOST)" 'systemctl --user --no-pager status karly'

restart:
	ssh "$(KARLY_HOST)" 'systemctl --user restart karly'

stop:
	ssh "$(KARLY_HOST)" 'systemctl --user stop karly'
