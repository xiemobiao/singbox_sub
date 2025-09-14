.PHONY: build up restart down logs update backup

build:
	docker compose build

up:
	docker compose up -d

restart:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

update:
	bash scripts/update.sh

backup:
	@mkdir -p data && \
	if [ -f data/subscriptions.db ]; then \
	  cp -a data/subscriptions.db data/subscriptions.db.bak-`date +%Y%m%d-%H%M%S` && \
	  echo "Backup created" ; \
	else \
	  echo "No DB to backup" ; \
	fi

