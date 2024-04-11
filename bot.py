import docker
import os
import logging
import time
import discord
import paramiko
import subprocess
from threading import Thread
from wakeonlan import send_magic_packet
from dotenv import load_dotenv

#TODO: make a docker whitelist to avoid exposing unwanted dockers to bot commands
#TODO: make a Thread to run update_status() every x seconds as long as the pc is reachable via ping -> allows auto shutdown on server side if available

#Setup----------------------------
logging.basicConfig(filename="Bot.log",
                    encoding="utf-8",
                    level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt='%d-%m-%y %H:%M:%S'
)
#Default values-------------------
SSH = paramiko.SSHClient()
SSH.set_missing_host_key_policy(paramiko.AutoAddPolicy())
WHITELIST = []

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
    TIMEOUT = os.getenv('TIMEOUT', 6)
    try:
        with open(WHITELIST_PATH) as file:
            WHITELIST = file.readlines()
            WHITELIST = list(map(lambda i: i.rstrip(), WHITELIST))
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
        i = 1
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

def is_up() -> bool: #WARN: linux specific code!
    #TODO: make is_up() using a subprocess.call(["ping", "-c", "1", HOSTNAME])
    ping = subprocess.run(['ping', '-c', '1', HOSTNAME])
    return ping.returncode == 0

def suspend_server():
    i = 1
    while i < TIMEOUT:
        try:
            SSH.connect(hostname=HOSTNAME, username=USERNAME, key_filename=KEY_PATH)
            stdin_, stdout_, stderr_ = SSH.exec_command("systemctl suspend")
            i = TIMEOUT
            logging.info("systemctl suspend was executed")
        except paramiko.ssh_exception.SSHException as e:
            logging.info("Failed to suspend server on attempt " + str(i) + " of " + str(TIMEOUT - 1))
            logging.info(e)
            i = i + 1
            time.sleep(2)
            if SSH:
                SSH.close()
    if SSH:
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
    if len(presence) == 0:
        suspend_server()
    await bot.change_presence(activity=discord.Game(name=str(presence)))

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
    await update_status()
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
    await update_status()
    await ctx.followup.send(response, ephemeral=True)

def threadcheck():
    while True:
        time.sleep(300) #5 minute sleep
        if is_up():
            running = []
            try:
                client = get_client()
                containertlist = client.containers.list()
                for i in containertlist:
                    if i.status == "running":
                        running.append(i.name)
            except ConnectionError:
                pass
            if len(running) == 0:
                suspend_server()
            else:
                logging.info(f"running containers: {running}")

            


#MAIN----------------------
def main():
    t = Thread(target=threadcheck)
    t.start()
    bot.run(TOKEN)
if __name__ == "__main__":
    main()