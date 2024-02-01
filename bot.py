import docker
import os
import logging
import time
import discord
import paramiko
from wakeonlan import send_magic_packet
from dotenv import load_dotenv

#Setup----------------------------
logging.basicConfig(filename="Bot.log")
SSH = paramiko.SSHClient()
load_dotenv()
SERVER_MAC_ADDRESS = os.getenv('SERVER_MAC_ADDRESS')
TOKEN = os.getenv('DISCORD_TOKEN')
HOSTNAME = os.getenv('HOSTNAME')
KEY_PATH = os.getenv('KEY_PATH')
USERNAME = os.getenv('USERNAME')

TIMEOUT = 15
def get_client() -> docker.DockerClient: #WARN: can raise ConnectionError
    try:
        client = docker.DockerClient(base_url="tcp://192.168.178.32:2375", use_ssh_client=False)
    except docker.errors.DockerException as e:
        i = 0
        while i < TIMEOUT:
            send_magic_packet(SERVER_MAC_ADDRESS)
            try:
                client = docker.DockerClient(base_url="tcp://192.168.178.32:2375", use_ssh_client=False)
            except docker.errors.DockerException:
                logging.debug("connetion attempt" + str(i) + " failed.")
                i = i + 1
                time.sleep(2)
                continue
            i = TIMEOUT
        if client == None:
            logging.error("could wake up server within timeout.")
            raise ConnectionError
        logging.debug("docker client connected.")
    return client

def suspend_server():
    i = 0
    while i < TIMEOUT:
        try:
            SSH.connect(hostname=HOSTNAME, username=USERNAME, pkey=KEY_PATH)
            SSH.exec_command("systemctl suspend")
            i = TIMEOUT
        except:
            logging.info("Failed to suspend server on attempt " + str(i) + " of " + str(TIMEOUT))
            i = i + 1

def is_up():
    i = 0
    while i < TIMEOUT:
        try:
            SSH.connect(hostname=HOSTNAME, username=USERNAME, pkey=KEY_PATH)
            if SSH.get_transport() is not None:
                return SSH.get_transport().is_active()
        except:
            i = i + 1
    return False

def reload_containers() -> list: #WARN: can raise ConnectionError
    ret = []
    client = get_client()
    containers = client.containers.list("all")
    for i in containers:
        ret.append(i.name)
    return ret


        
CONTAINERS = reload_containers()
bot = discord.Bot()

async def update_status() -> None:
    presence = []
    try:
        client = get_client()
        containertlist = client.containers.list()
        for i in containertlist:
            if i.status == "running":
                presence.append(i.name)
    except ConnectionError:
        pass
    if len(presence) == 0 and is_up():
        suspend_server()
    await bot.change_presence(activity=discord.Game(name=str(presence)))

#Bot command Def------------------
@bot.command(description="starts a server")
async def start(ctx, server: discord.Option(str, choices=CONTAINERS)):
    logging.info(f"[{server}] {time.localtime()} {ctx.author} used the start command\n")
    await ctx.response.defer(ephemeral=True)
    try:
        client = get_client()
        client.containers.get(server).start()
        response = "starting server."
    except ConnectionError:
        response = "could not wake main server. Please try again later"
    await update_status()
    await ctx.followup.send(response, ephemeral=True)

@bot.command(description="stops a server")
async def stop(ctx, server: discord.Option(str, choices=CONTAINERS)):
    logging.info(f"[{server}] {time.localtime()} {ctx.author} used the stop command\n")
    await ctx.response.defer(ephemeral=True)
    try:
        client = get_client()
        client.containers.get(server).stop()
        response = "stopping server."
    except ConnectionError:
        response = "could not wake main server. Please try again later"
    await update_status()
    await ctx.followup.send(response, ephemeral=True)


#MAIN----------------------
async def main():
    await update_status()
    bot.run(TOKEN)
if __name__ == "__main__":
    main()