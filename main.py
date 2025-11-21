import os
import signal
import subprocess
import threading
import fastapi.responses
import uvicorn
from pathlib import Path
from typing import Any
from batata import list_servers as servers_list, load_servers, list_mods as mods, JSONManager
from fastapi import FastAPI, HTTPException, Header

SERVERS_PATH = str(Path('~/Desktop/Coisas Do Decaptado/Mine Server/').expanduser())
SERVERS_CONFIGS = str(Path('~/Desktop/Coisas Do Decaptado/MineServer-Controller').expanduser())
API_KEYS: dict[str, str] = {
    'paper': 'Survivors',
    'forge': 'Survivors-Mods'
}


def verify_key(api_key: str) -> str:
    if api_key not in API_KEYS:
        raise HTTPException(
            status_code=401,
            detail=f'API key {api_key} invalida verifique digitação e tente novamente\nInvalid API key'
        )
    return API_KEYS[api_key]


async def validate(mine_server: str, api_key: str = Header(...)):
    expected_server = API_KEYS.get(api_key)

    if not expected_server:
        raise HTTPException(
            status_code=404,
            detail=f'API key "{api_key}" inválida'
        )

    if mine_server != expected_server:
        raise HTTPException(
            status_code=403,
            detail=f'API key não coresponde ao servidor'
                   f'Chave "{api_key}" serve para o server "{expected_server}"'
                   f'mas você tentou usar para "{mine_server}"'
        )


app = FastAPI(title='Batata API')


@app.get("/")
async def root() -> fastapi.responses.RedirectResponse:
    return fastapi.responses.RedirectResponse(url='/docs')


@app.get('/minecraft/servers')
async def list_servers():
    return servers_list(arquivo='servers.json',
                        path=SERVERS_CONFIGS)


@app.get('/server/{mine_server}/mods')
async def list_mods(mine_server: str, api_key: str = Header(...)):
    await validate(mine_server, api_key)
    path = str(Path(SERVERS_PATH) / 'Forge')
    print(path)

    return mods(server_path=path, server_config_path=SERVERS_CONFIGS, server=mine_server)


@app.get('/server/{mine_server}/status')
async def status_server(mine_server: str):
    info: JSONManager = JSONManager(name='servers_info.json')
    for server_info in info.read():
        if server_info['server'] == mine_server:
            return {'status': server_info['status']}

    return {}


@app.post('/server/{mine_server}/start')
async def start_server(mine_server: str, api_key: str = Header(...)) -> dict[str, Any]:
    await validate(mine_server=mine_server, api_key=api_key)

    servers = load_servers(path=SERVERS_CONFIGS)
    server_config = next((s for s in servers if s['server_name'] == mine_server), None)

    if not server_config:
        raise HTTPException(
            status_code=404,
            detail='Servidor não encontrado!\nServer not found'
        )

    jar_path = Path(server_config['server_path']).expanduser() / server_config['jar_name']
    proxy_path = Path(server_config['server_path']).expanduser() / server_config['proxy_name']

    process = subprocess.Popen(
        [
            'java',
            '-Xmx4096M',
            '-Xms1024M',
            '-jar',
            str(jar_path),
            'nogui'
        ],
        cwd=str(Path(server_config["server_path"]).expanduser()),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    proxy = subprocess.Popen(
        [str(proxy_path)],
        cwd=str(Path(server_config["server_path"]).expanduser()),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    # Thread para não travar a API (OPCIONAL, mas recomendado)
    def stream_output(proc, prefix):
        for line in proc.stdout:
            print(f"{prefix} {line}", end="")

    threading.Thread(target=stream_output, args=(process, "[SERVER]"), daemon=True).start()
    threading.Thread(target=stream_output, args=(proxy, "[PROXY]"), daemon=True).start()

    save_info: JSONManager = JSONManager(name='servers_info.json')
    save_info.write({
        "status": "started",
        "server": mine_server,
        "pid": process.pid,
        "proxy": server_config['proxy_name'],
        "proxy-pid": proxy.pid
    })

    return {
        "status": "started",
        "server": mine_server,
        "pid": process.pid,
        "proxy": server_config['proxy_name'],
        "proxy-pid": proxy.pid
    }


@app.post('/server/{mine_server}/stop')
async def stop_server(mine_server: str, api_key: str = Header(...)):
    await validate(mine_server=mine_server, api_key=api_key)

    info: JSONManager = JSONManager(name='servers_info.json')
    for server_info in info.read():
        if server_info['server'] == mine_server:
            if server_info['status'] != 'stopped':
                try:
                    os.kill(server_info['pid'], signal.SIGKILL)
                    os.kill(server_info['proxy-pid'], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            info.update('server', mine_server, 'status', 'stopped')
            info.update('server', mine_server, 'pid', None)
            info.update('server', mine_server, 'proxy-pid', None)
            return {
                'status': server_info['status'],
                'server': server_info['server']
            }
    return {}


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=8000)