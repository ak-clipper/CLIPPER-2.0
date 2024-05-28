aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin 058264536995.dkr.ecr.eu-central-1.amazonaws.com
docker build -t clipper .
docker tag clipper:latest 058264536995.dkr.ecr.eu-central-1.amazonaws.com/clipper:latest
docker push 058264536995.dkr.ecr.eu-central-1.amazonaws.com/clipper:latest