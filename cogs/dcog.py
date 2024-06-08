
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

class Config():
    def __init__(self):
        self.load_dotenv()
    def load_dotenv(self) -> bool:
        logging.debug("Loading Config")
        load_dotenv()
        self.SERVER_MAC_ADDRESS = os.getenv('SERVER_MAC_ADDRESS', "00:80:41:ae:fd:7e")
        self._TOKEN = os.getenv('DISCORD_TOKEN', "123456789101112131415161718192021222324252627282930")
        self.HOSTNAME = os.getenv('HOSTNAME', "localhost")
        self.DOCKER_PORT = os.getenv('DOCKER_PORT', "2375")
        self.KEY_PATH = os.getenv('KEY_PATH', "~/.ssh/id_rsa")
        self.USERNAME = os.getenv('USERNAME', "User")
        self.WHITELIST_PATH = os.getenv('WHITELIST_PATH', "whitelist.txt")
        self.TIMEOUT = int(os.getenv('TIMEOUT', 6))
        try:
            with open(self.WHITELIST_PATH) as file:
                self.WHITELIST = list(map(lambda i: i.rstrip(), file.readlines())) #strip whitespaces, otherwise whitelist won't accept docker names in filter
        except IOError:
            logging.warning("failed to read whitelist")
            return False
        return True
    def get_discord_token(self):
        logging.debug("discord token was fetched from config")
        return self._TOKEN

class DockerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config()
        self.update_status.start()
        self.SSH = paramiko.SSHClient()
        self.SSH.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.get_containers() # sets global CONTAINERS variable. cannot use self.CONTAINERS for slash commands, since self reference does not exist yet
    def cog_unload(self):
        self.update_status.cancel()
    
    #Help command Def-----------------
    @tasks.loop(minutes=1)
    async def update_status(self) -> None:
        if self.is_up():
            presence = []
            try:
                presence, running_containers = self.get_containers()
            except ConnectionError:
                pass
            if running_containers == 0:
                self.suspend_server()
                await self.bot.change_presence(activity=None)
                return
            logging.debug(f"[update]: {presence}")
            await self.bot.change_presence(activity=discord.Game(name=str(presence)))
    def get_containers(self):
        client = self.get_client()
        containertlist = client.containers.list("all")
        running_containers = len(client.containers.list())
        presence = []
        whitelisted_containers = []
        for i in containertlist:
            if self.in_whitelist(i.name):
                whitelisted_containers.append(i.name)
                if i.status == "running":
                    presence.append(i.name)
        self.CONTAINERS = whitelisted_containers
        global CONTAINERS
        CONTAINERS = self.CONTAINERS
        logging.debug(f"loaded {self.CONTAINERS} as list of available Servers")
        return presence, running_containers

    def wake_server(self, mac=None) -> bool:
        if mac == None:
            mac = self.config.SERVER_MAC_ADDRESS
        i: int = 1
        while i < self.config.TIMEOUT and not self.is_up():
            logging.debug(f"wake attempt {i} on {mac}")
            send_magic_packet(mac)
            time.sleep(2)
            i += 1
        return self.is_up()

    def get_client(self) -> docker.DockerClient: #WARN: can raise ConnectionError
        if self.is_up():
            client = docker.DockerClient(base_url=f"tcp://{self.config.HOSTNAME}:{self.config.DOCKER_PORT}", use_ssh_client=False)
        elif self.wake_server():
            client = docker.DockerClient(base_url=f"tcp://{self.config.HOSTNAME}:{self.config.DOCKER_PORT}", use_ssh_client=False)
        else:
            logging.error("could not wake server within timeout.")
            raise ConnectionError
        logging.debug("docker client connected.")
        return client

    def is_up(self) -> bool: #WARN: linux specific code! -> Windows implementation of ping is different!
        ping = subprocess.run(['ping', '-c', '1', self.config.HOSTNAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ping.returncode == 0

    def suspend_server(self):
        i = 1
        while i < self.config.TIMEOUT:
            try:
                self.SSH.connect(hostname=self.config.HOSTNAME, username=self.config.USERNAME, key_filename=self.config.KEY_PATH) #bot currently only supports keyauth. keyauth with password on id_rsa file not supported either.
                _stdin, _stdout, _stderr = self.SSH.exec_command("systemctl suspend")
                i = self.config.TIMEOUT
                logging.info("systemctl suspend was executed")
            except paramiko.ssh_exception.SSHException as e:
                logging.info("Failed to suspend server on attempt " + str(i) + " of " + str(self.config.TIMEOUT - 1))
                logging.info(e)
                self.SSH.close()
                i = i + 1
                time.sleep(2)
        if i == self.config.TIMEOUT - 1:
            logging.error(f"failed to suspend server after {self.config.TIMEOUT} tries")
        self.SSH.close()

    def in_whitelist(self, name: str) -> bool:
        if ("*" in self.config.WHITELIST): #possibly remove this check, because this turns whitelist into blacklist. blacklist is easier to accidentally expose containers with.
            return True
        return (name in self.config.WHITELIST)

    def container_init(self):
        client = self.get_client()
        containertlist = client.containers.list("all")
        temp_containers = []
        for i in containertlist:
            if self.in_whitelist(i.name):
                temp_containers.append(i.name)
        global CONTAINERS
        CONTAINERS = temp_containers
    #Bot command Def------------------
    @commands.command(description="starts a server")
    async def start(self, ctx, server: discord.Option(str, choices=CONTAINERS)): # type: ignore
        logging.info(f"[{server}] {ctx.author} used the start command")
        await ctx.response.defer(ephemeral=True)
        try:
            client = self.get_client()
            # enforce container limit to avoid maxing out memory
            running_containers = 0
            for i in client.containers.list("all"):
                if i.status == "running" and self.in_whitelist(i.name):
                    running_containers += 1
            if running_containers > 1:
                response = f"{running_containers} gameserver(s) are running. To avoid performance problems, no more servers will be started."
            else:
                client.containers.get(server).start()
                response = "starting server."
        except ConnectionError:
            response = "could not wake main server. Please try again later"

        await ctx.followup.send(response, ephemeral=True)

    @commands.command(description="stops a server")
    async def stop(self, ctx, server: discord.Option(str, choices=CONTAINERS)): # type: ignore
        logging.info(f"[{server}] {ctx.author} used the stop command")
        await ctx.response.defer(ephemeral=True)
        try:
            client = self.get_client()
            client.containers.get(server).stop()
            response = "stopping server."
        except ConnectionError:
            response = "could not wake main server. Please try again later"
        await ctx.followup.send(response, ephemeral=True)