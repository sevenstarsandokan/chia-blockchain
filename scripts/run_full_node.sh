. .venv/bin/activate
. scripts/common.sh

# Starts a full node
_run_bg_cmd python -m src.server.start_full_node --port=8444 --connect_to_farmer=True --connect_to_timelord=True --rpc_port=8555
_run_bg_cmd python -m src.ui.start_ui --port=8222 --rpc_port=8555

wait
