# Why was this made?
This Bot is meant to be used in connection with a very cheap to run and low power system. 
By having such a system control a more powerful system and hibernating it, the powerbill is made much easier to digest while the gameservers for friends stay available even,
when a goblin on the other side of the world wants to start playing at midnight.
# What do i need to watch out for
- The less powerful "Helper Server" running this bot (likely a raspberrypi) and the more powerful "Game Server" should be running linux.
- Wake-On-Lan must be set up and working on the "Game Server", otherwise availability for you and your friends cannot be guaranteed.
- The Discord bot MUST be private and MUSTN'T be deployed in a discord-server of people you do not know/trust. Preferably you should be the owner of the used discord server and should NEVER allow anyone you do not know and trust to join.
- NEVER disclose the discord token as per discords advice and thus NEVER show anyone the contents of your .env file as it holds said token.
