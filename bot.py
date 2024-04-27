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

#TODO: use RotatingFileHandler
#Setup----------------------------
logging.basicConfig(filename="log/bot.log",
                    encoding="utf-8",
                    level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt='%d-%m-%y %H:%M:%S'
)


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
                
def wake_server(mac=SERVER_MAC_ADDRESS) -> bool:
    i: int = 1
    while i < TIMEOUT and not is_up():
        logging.debug(f"wake attempt {i} on {mac}")
        send_magic_packet(mac)
        time.sleep(2)
        i += 1
    return is_up()

def get_client() -> docker.DockerClient: #WARN: can raise ConnectionError
    if is_up():
        client = docker.DockerClient(base_url=f"tcp://{HOSTNAME}:{DOCKER_PORT}", use_ssh_client=False)
    elif wake_server():
        client = docker.DockerClient(base_url=f"tcp://{HOSTNAME}:{DOCKER_PORT}", use_ssh_client=False)
    else:
        logging.error("could not wake server within timeout.")
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

def in_whitelist(name: str) -> bool:
    if ("*" in WHITELIST): #possibly remove this check, because this turns whitelist into blacklist. blacklist is easier to accidentally expose containers with.
        return True
    return (name in WHITELIST)


        
bot = discord.Bot()

class UCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.update_status.start()
    def cog_unload(self):
        self.update_status.cancel()
    @tasks.loop(minutes=1)
    async def update_status(self) -> None:
        if is_up():
            presence = []
            try:
                client = get_client()
                containertlist = client.containers.list()
                for i in containertlist:
                    if i.status == "running" and in_whitelist(i.name):
                        presence.append(i.name)
            except ConnectionError:
                pass
            if len(presence) == 0:
                suspend_server()
                await self.bot.change_presence(activity=None)
                return
            logging.debug(f"[update]: {presence}")
            await self.bot.change_presence(activity=discord.Game(name=str(presence)))

#Bot command Def------------------
@bot.command(description="starts a server")
async def start(ctx, server: discord.Option(str, choices=CONTAINERS)): # type: ignore
    logging.info(f"[{server}] {ctx.author} used the start command")
    await ctx.response.defer(ephemeral=True)
    try:
        client = get_client()
        # enforce container limit to avoid maxing out memory
        running_containers = 0
        for i in client.containers.list():
            if i.status == "running" and in_whitelist(i.name):
                running_containers += 1
        if running_containers > 1:
            response = f"{running_containers} gameserver(s) are running. To avoid performance problems, no more servers will be started."
        else:
            client.containers.get(server).start()
            response = "starting server."
    except ConnectionError:
        response = "could not wake main server. Please try again later"

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

    # await update_status()
    await ctx.followup.send(response, ephemeral=True)
@bot.event
async def on_ready():
    bot.add_cog(UCog(bot))

#MAIN----------------------
def main():
    # bot.add_cog(UCog(bot))
    bot.run(TOKEN)
if __name__ == "__main__":
    main()