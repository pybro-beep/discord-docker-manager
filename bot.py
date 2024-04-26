import docker
import os
import logging
import time
import discord
from discord.ext import tasks, commands
import paramiko
import subprocess
from threading import Thread
from wakeonlan import send_magic_packet
from dotenv import load_dotenv


#Setup----------------------------
logging.basicConfig(filename="bot.log",
                    encoding="utf-8",
                    level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt='%d-%m-%y %H:%M:%S'
)

#move discord log into different file (spams socket reconnections etc. on long runtime)
logging.getLogger('discord').addHandler(logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w'))

#Default values-------------------
SSH = paramiko.SSHClient()
SSH.set_missing_host_key_policy(paramiko.AutoAddPolicy())
WHITELIST = []
TIMEOUT: int = 6 #Type annotations have to be made in the scope that owns the variable. -> load_config may not add type to TIMEOUT

#override default ---------------

def load_config():
    global SERVER_MAC_ADDRESS, TOKEN, HOSTNAME, DOCKER_PORT, KEY_PATH, USERNAME, WHITELIST_PATH, WHITELIST, TIMEOUT
    logging.info("Loading Config")
    load_dotenv()
    SERVER_MAC_ADDRESS = os.getenv('SERVER_MAC_ADDRESS', "00:80:41:ae:fd:7e")
    TOKEN = os.getenv('DISCORD_TOKEN', "123456789101112131415161718192021222324252627282930")
    HOSTNAME = os.getenv('HOSTNAME', "localhost")
    DOCKER_PORT = os.getenv('DOCKER_PORT', "2375")
    KEY_PATH = os.getenv('KEY_PATH', "~/.ssh/id_rsa")
    USERNAME = os.getenv('USERNAME', "User")
    WHITELIST_PATH = os.getenv('WHITELIST_PATH', "whitelist.txt")
    TIMEOUT = int(os.getenv('TIMEOUT', 6))
    try:
        with open(WHITELIST_PATH) as file:
            WHITELIST = file.readlines()
            WHITELIST = list(map(lambda i: i.rstrip(), WHITELIST)) #strip whitespaces, otherwise whitelist won't accept docker names in filter
    except IOError:
        logging.warning("failed to read whitelist")
    if "*" in WHITELIST:
        logging.warning("The * operator was used in the Whitelist. All dockers will be exposed!")
        WHITELIST = ["*"]
    logging.info("loaded Whitelist: " + str(WHITELIST))
load_config()
                

def get_client() -> docker.DockerClient: #WARN: can raise ConnectionError
    try:
        client = docker.DockerClient(base_url=f"tcp://{HOSTNAME}:{DOCKER_PORT}", use_ssh_client=False)
    except docker.errors.DockerException as e:
        i: int = 1
        while i < TIMEOUT:
            send_magic_packet(SERVER_MAC_ADDRESS)
            try:
                client = docker.DockerClient(base_url=f"tcp://{HOSTNAME}:{DOCKER_PORT}", use_ssh_client=False)
            except docker.errors.DockerException:
                logging.debug("connetion attempt" + str(i) + " failed.")
                i = i + 1
                time.sleep(5) #wakeup can take a while especially if wireless connection is used
                continue
            i = TIMEOUT
        if client == None:
            logging.error("could wake up server within timeout.")
            raise ConnectionError
        logging.debug("docker client connected.")
    return client

def is_up() -> bool: #WARN: linux specific code! -> Windows implementation of ping is different!
    ping = subprocess.run(['ping', '-c', '1', HOSTNAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ping.returncode == 0

def suspend_server():
    i = 1
    while i < TIMEOUT:
        try:
            SSH.connect(hostname=HOSTNAME, username=USERNAME, key_filename=KEY_PATH) #bot currently only supports keyauth. keyauth with password on id_rsa file not supported either.
            _stdin, _stdout, _stderr = SSH.exec_command("systemctl suspend")
            i = TIMEOUT
            logging.info("systemctl suspend was executed")
        except paramiko.ssh_exception.SSHException as e:
            logging.info("Failed to suspend server on attempt " + str(i) + " of " + str(TIMEOUT - 1))
            logging.info(e)
            SSH.close()
            i = i + 1
            time.sleep(2)
    if i == TIMEOUT - 1:
        logging.error(f"failed to suspend server after {TIMEOUT} tries")
    SSH.close()

def reload_containers() -> list: #WARN: can raise ConnectionError
    ret = []
    client = get_client()
    containers = client.containers.list("all")
    load_all = "*" in WHITELIST
    for i in containers:
        if load_all:
            ret.append(i.name)
            continue

        if i.name in WHITELIST:
            ret.append(i.name)
        else:
            logging.info(f"{i.name} is not in {WHITELIST_PATH}. ignoring")
    return ret


        
CONTAINERS = reload_containers()
bot = discord.Bot()
class UCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    @tasks.loop(minutes=1)
    async def update_status(self) -> None:
        if is_up():
            presence = []
            try:
                client = get_client()
                containertlist = client.containers.list()
                for i in containertlist:
                    if i.status == "running":
                        presence.append(i.name)
            except ConnectionError:
                pass
            if len(presence) == 0:
                suspend_server()
                await self.bot.change_presence(activity=None)
                return
            logging.info(f"[update]: {presence}")
            await self.bot.change_presence(activity=discord.Game(name=str(presence)))

#Bot command Def------------------
@bot.command(description="starts a server")
async def start(ctx, server: discord.Option(str, choices=CONTAINERS)): # type: ignore
    logging.info(f"[{server}] {ctx.author} used the start command")
    await ctx.response.defer(ephemeral=True)
    try:
        client = get_client()
        client.containers.get(server).start()
        response = "starting server."
    except ConnectionError:
        response = "could not wake main server. Please try again later"

    global CONTAINERS
    CONTAINERS = reload_containers()
    logging.info(f"loaded containers: {CONTAINERS}")
    # await update_status()
    await ctx.followup.send(response, ephemeral=True)

@bot.command(description="stops a server")
async def stop(ctx, server: discord.Option(str, choices=CONTAINERS)): # type: ignore
    logging.info(f"[{server}] {ctx.author} used the stop command")
    await ctx.response.defer(ephemeral=True)
    try:
        client = get_client()
        client.containers.get(server).stop()
        response = "stopping server."
    except ConnectionError:
        response = "could not wake main server. Please try again later"

    global CONTAINERS
    CONTAINERS = reload_containers()
    logging.info(f"loaded containers: {CONTAINERS}")
    # await update_status()
    await ctx.followup.send(response, ephemeral=True)


#MAIN----------------------
def main():
    bot.add_cog(UCog(bot))
    bot.run(TOKEN)
if __name__ == "__main__":
    main()