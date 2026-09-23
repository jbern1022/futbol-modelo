# Grafana config (source of truth)

Grafana runs on docker-host as part of the `~/monitoring` compose
stack (separate from this repo) -- these files are the checked-in
source of truth for its provisioning config, deployed by hand:

```bash
# Datasource (docker-host, joe-writable):
scp grafana/provisioning/datasources/loki.yml docker:~/monitoring/grafana-provisioning/datasources/loki.yml

# Dashboard provider config -- root-owned on docker-host, needs sudo:
scp grafana/provisioning/dashboards/dashboards.yml docker:/tmp/dashboards.yml
ssh docker 'sudo cp /tmp/dashboards.yml ~/monitoring/grafana-provisioning/dashboards/dashboards.yml && \
             sudo chown root:root ~/monitoring/grafana-provisioning/dashboards/dashboards.yml && \
             sudo chmod 644 ~/monitoring/grafana-provisioning/dashboards/dashboards.yml'

# Dashboard JSON (docker-host, joe-writable):
scp grafana/dashboards/futbol-modelo-logs.json docker:~/monitoring/dashboards/futbol-modelo/futbol-modelo-logs.json

# Pick up all changes:
ssh docker 'docker restart grafana'
```

`dashboards.yml`'s provider watches `/var/lib/grafana/dashboards`
(host: `~/monitoring/dashboards`) every 30s and auto-reloads on
change, so after the one-time provider setup above, updating
`futbol-modelo-logs.json` (or adding a new dashboard file next to it)
only needs the `scp` to the joe-writable `dashboards/` path -- no
restart, no sudo.

## Why the Loki datasource URL is a bare LAN IP

Loki (`~/loki` on docker-host) and Grafana (`~/monitoring`) are two
separate, unconnected Docker Compose stacks -- no shared network, so
`http://loki:3100` doesn't resolve from Grafana's container. Same
constraint already hit for ntfy/pgbouncer: `http://192.168.4.20:3100`
(docker-host's LAN IP) is what actually works.

## Log shipping

The existing Promtail on docker-host (`~/loki/promtail-config`) only
scrapes docker-host's own Docker socket -- it has never seen the k3s
cluster. `k8s/promtail.yaml` in this repo is a second, independent
Promtail (a cluster DaemonSet) that ships k3s pod logs to the same
Loki instance. See that file's own header comment for the full design,
including why it needs a `cri:` pipeline stage before `json:`.
