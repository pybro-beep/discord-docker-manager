import docker
import os
import logging
import time
import discord
from wakeonlan import send_magic_packet
from dotenv import load_dotenv

#Setup----------------------------
logging.basicConfig(filename="Bot.log")
load_dotenv()
SERVER_MAC_ADDRESS = os.getenv('SERVER_MAC_ADDRESS')
TOKEN = os.getenv('DISCORD_TOKEN')

TIMEOUT = 5
def get_client() -> docker.DockerClient: #WARN: can raise ConnectionError
    try:
        client = docker.DockerClient(base_url="tcp://192.168.178.32:2375", use_ssh_client=False)
    except docker.errors.APIError as e:
        i = 0
        while i < TIMEOUT:
            send_magic_packet(SERVER_MAC_ADDRESS)
            try:
                client = docker.DockerClient(base_url="tcp://192.168.178.32:2375", use_ssh_client=False)
            except docker.errors.APIError:
                logging.debug("connetion attempt" + i + " failed.")
                i = i + 1
                continue
            i = TIMEOUT
        if client == None:
            logging.error("could wake up server within timeout.")
            raise ConnectionError
        logging.debug("docker client connected.")
        return client

def reload_containers(): #WARN: can throw ConnectionError
    ret = []
    client = get_client()
    client.containers.list()
    for i in list:
        ret.append(i.name)
    return ret


        
CONTAINERS = reload_containers()
bot = discord.Bot()

async def update_status() -> None:
    presence = []
    try:
        client = get_client()
        containertlist = client.containers.list
        for i in containertlist:
            if i.status == "running":
                presence.append(i.name)
    except ConnectionError:
        pass
    await bot.change_presence(activity=discord.Game(name=str(presence)))

#Bot command Def------------------
@bot.command(description="starts a server")
async def start(ctx, server: discord.Option(str, choices=CONTAINERS)):
    logging.info(f"[{server}] {time.localtime()} {ctx.author} used the start command\n")
    try:
        client = get_client()
        client.containers.get(server).start()
    except ConnectionError:
        response = "could not wake main server. Please try again later"
    await update_status()
    await ctx.respond(response, ephemeral=True)

@bot.command(description="starts a server")
async def stop(ctx, server: discord.Option(str, choices=CONTAINERS)):
    logging.info(f"[{server}] {time.localtime()} {ctx.author} used the start command\n")
    try:
        client = get_client()
        client.containers.get(server).stop()
    except ConnectionError:
        response = "could not wake main server. Please try again later"
    await update_status()
    await ctx.respond(response, ephemeral=True)