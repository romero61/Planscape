# Authors: 
# - RJ Sheperd (rsheperd@sig-gis.com)
# - George Silva (gsilva@sig-gis.com)

# User Systemd Service (see: ~/.config/systemd/user/planscape.service)
SERVICE=planscape
FORSYS_QUEUE=forsys-queue
CELERY_FORSYS=celery-forsys-worker
CELERY_DEFAULT=celery-default-worker

# Directory which NGINX serves up for planscape
PUBLIC_WWW_DIR=/var/www/html/planscape/

# Systemd User Control
SYS_CTL=systemctl --user
TAG=main

checkout:
	git fetch origin; \
	git switch main; \
	git pull origin main; \
	git checkout $(TAG)

taggit:
	git checkout main; \
	git pull origin main; \
	git tag -a $(VERSION); \
	git push origin --tags

install-dependencies-frontend:
	cd src/interface && npm install

compile-angular:
	cd src/interface && npm run build -- --configuration production --output-path=./dist/out

deploy-frontend: install-dependencies-frontend compile-angular
	cp -r ./src/interface/dist/out/** ${PUBLIC_WWW_DIR}

migrate:
	cd src/planscape && python3 manage.py migrate --no-input

load-conditions:
	cd src/planscape && python3 manage.py load_conditions

load-metrics:
	cd src/planscape && python3 manage.py load_metrics

load-rasters:
	cd src/planscape && python3 manage.py load_rasters

install-dependencies-backend:
	pip install -r src/planscape/requirements.txt

deploy-backend: install-dependencies-backend migrate load-conditions restart

deploy-all: deploy-backend deploy-frontend

start-forsys:
	${SYS_CTL} start ${FORSYS_QUEUE}

stop-forsys:
	${SYS_CTL} stop ${FORSYS_QUEUE}

status-forsys:
	${SYS_CTL} status ${FORSYS_QUEUE}

start-celery:
	${SYS_CTL} start ${CELERY_DEFAULT} --no-block
	${SYS_CTL} start ${CELERY_FORSYS} --no-block

stop-celery:
	${SYS_CTL} stop ${CELERY_DEFAULT}
	${SYS_CTL} stop ${CELERY_FORSYS}

status-celery:
	${SYS_CTL} status ${CELERY_DEFAULT}
	${SYS_CTL} status ${CELERY_FORSYS}

start:
	${SYS_CTL} start ${SERVICE}

stop:
	${SYS_CTL} stop ${SERVICE}

status:
	${SYS_CTL} status ${SERVICE}

reload:
	${SYS_CTL} daemon-reload

restart: reload stop stop-forsys stop-celery start start-forsys start-celery

nginx-restart:
	sudo service nginx restart

load-restrictions:
	cd src/planscape && sh bin/load_restrictions.sh