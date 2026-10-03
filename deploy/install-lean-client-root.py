#!/usr/bin/env python3
"""Install only the dedicated research SSH identity; never copies broker credentials."""
import json,os,pathlib,pwd,shutil,socket,subprocess

def main():
    if os.geteuid()!=0 or socket.gethostname().split('.')[0]!='a1347-m':raise SystemExit('Run with sudo on a1347-m')
    staging=pathlib.Path('/home/mjm2z/.local/state/stockwatch-lean-setup')
    key=staging/'id_ed25519';known=staging/'known_hosts'
    if not key.is_file() or not known.is_file():raise SystemExit('Stage the scoped research identity and verified host key first')
    # Validate the key without printing any private material.
    subprocess.run(['ssh-keygen','-y','-f',str(key)],check=True,stdout=subprocess.DEVNULL)
    lines=known.read_text().strip().splitlines()
    if len(lines)!=1 or not lines[0].startswith('192.168.4.33 ssh-ed25519 '):raise SystemExit('Expected the verified a1347-d Ed25519 host key')
    account=pwd.getpwnam('stock-watch');root=pathlib.Path('/etc/stock-watch')
    for source,name in [(key,'lean_runner_ed25519'),(known,'lean_known_hosts')]:
        destination=root/name
        if destination.exists() and destination.read_bytes()!=source.read_bytes():raise SystemExit('Existing LEAN identity differs; review before replacing')
    config=root/'lean-runner.json'
    desired={'host':'lean-submit@192.168.4.33','expected_image':'quantconnect/lean@sha256:383b6540839f6e111b451a3d92919edfdb8ffbfdeeb85325491631a36ca58082'}
    if config.exists() and json.loads(config.read_text())!=desired:raise SystemExit('Existing runner configuration differs; review before replacing')
    for source,name in [(key,'lean_runner_ed25519'),(known,'lean_known_hosts')]:
        destination=root/name;shutil.copyfile(source,destination);os.chown(destination,account.pw_uid,account.pw_gid);destination.chmod(0o600)
    config.write_text(json.dumps(desired));os.chown(config,account.pw_uid,account.pw_gid);config.chmod(0o600)
    print('Scoped LEAN identity configured. The reviewed application release installs the bridge service.')
if __name__=='__main__':main()
