# Makefile for managing the Proxy Bot Docker container

.PHONY: build up down logs restart clean

# Build the docker image
build:
	docker compose build

# Start the container in detached mode
up:
	docker compose up -d

# Stop and remove the container
down:
	docker compose down

# View logs
logs:
	docker compose logs -f

# Restart the container
restart: down up

# Clean up (removes containers and images)
clean:
	docker compose down --rmi all
