from math import ceil
from redbot.core import commands
from redbot.core import Config
from redbot.core.utils.chat_formatting import box
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, close_menu
from redbot.core.bot import Red
from discord.ext import tasks
from prettytable import PrettyTable
from datetime import time, date, datetime
import prettytable, discord, logging

log = logging.getLogger("red.gradient-cogs.recurringmessages")

class RecurringMessages(commands.Cog):
	"""Send recurring messages to a channel on an interval."""
	def __init__(self, bot : Red):
		super().__init__()
		self.bot: Red = bot
		self.config = Config.get_conf(self, identifier=98766212374527)
		self.config.register_guild(reminders=[], last_id=0)
		self.loop.start()

	def cog_unload(self):
		self.loop.cancel()
		return super().cog_unload()

	def create_reminder_data(self, id: int, channel_id: int, message: str, time: str, last_sent: str) -> dict:
		return { "id": id, "channel_id": channel_id, "message": message , "time": time, "last_sent": last_sent }

	@commands.guild_only()
	@commands.group(aliases=["recurringmessages"])
	async def recurring(self, ctx: commands.Context):
		"""Group command for recurring messages."""
		pass

	@commands.guildowner_or_permissions(administrator=True)
	@recurring.group(autohelp=False)
	async def add(self, ctx: commands.Context, channel: discord.TextChannel, message_time: str, message: str):
		"""Add a new recurring message to this server. Times are specified in UTC."""
		await ctx.trigger_typing()

		reminder_time: time

		try:
			reminder_time = time.fromisoformat(message_time)
		except Exception as e:
			await ctx.send(f"Invalid time \"{message_time}\".")
			await ctx.react_quietly(reaction="❎")
			log.exception(e)
			return

		actual_time = reminder_time.isoformat("minutes")
		current_time: time = datetime.utcnow().timetz()
		last_sent = str(date.min)

		if(actual_time < current_time):
			last_sent = str(datetime.utcnow().date)

		async with self.config.guild(ctx.guild).reminders() as guild_reminders:
			new_id = (await self.config.guild(ctx.guild).last_id()) + 1
			reminder = self.create_reminder_data(new_id, channel.id, message, actual_time, last_sent)
			guild_reminders.append(reminder)
			await self.config.guild(ctx.guild).last_id.set(new_id)

		await ctx.tick()
		await ctx.reply("I will send that message there every day at %s UTC." % actual_time)

	@commands.guildowner_or_permissions(administrator=True)
	@recurring.group(aliases=["remove"], autohelp=False)
	async def delete(self, ctx: commands.Context, id: int):
		"""Delete a recurring message on this server."""
		async with self.config.guild(ctx.guild).reminders() as guild_reminders:
			guild_reminders: list[dict]
			for reminder in guild_reminders:
				if(reminder["id"] == id):
					guild_reminders.remove(reminder)
					await ctx.tick()
					return
		
		await ctx.react_quietly(reaction="❎")

	@commands.guildowner_or_permissions(administrator=True)
	@recurring.group(autohelp=False)
	async def list(self, ctx: commands.Context):
		"""Lists all recurring messages in the server. All times are in UTC."""
		reminders: list[dict] = await self.config.guild(ctx.guild).reminders()

		if(len(reminders) == 0):
			await ctx.send(f"This server does not have any recurring messages.")
			return

		embed_requested = await ctx.embed_requested()
		base_embed = discord.Embed()
		base_embed.set_author(name=f"Recurring Messages for \"{str(ctx.guild)}\"")
		base_table = PrettyTable(field_names=["ID", "Channel", "Time", "Message"])
		base_table.set_style(prettytable.PLAIN_COLUMNS)
		base_table.right_padding_width = 2
		base_table.align = "l"

		base_table.align["Message"] = "m"

		temp_table = base_table.copy()

		pages = []

		def make_embed():
			nonlocal temp_table, pages
			msg = temp_table.get_string()

			if(embed_requested):
				embed = base_embed.copy()
				embed.description = box(msg, lang="md")
				embed.set_footer(text=f"Page {len(pages)+1}/{ceil(len(reminders)/10)}")
				pages.append(embed)
			else:
				pages.append(box(msg, lang="md"))

			temp_table = base_table.copy()

		for idx, reminder in enumerate(reminders, start=1):
			msg = reminder["message"]

			if(len(msg) > 20):
				msg = msg[:18] + "..."

			reminder_id = str(reminder["id"])
			channel_id = reminder["channel_id"]
			channel = self.bot.get_channel(channel_id)

			if(channel == None):
				channel = channel_id
			else:
				channel = str(channel)

			temp_table.add_row([f"#{reminder_id}", f"#{channel}", reminder["time"], msg])
			
			if(idx % 10 == 0):
				make_embed()

		if(len(pages) != ceil(len(reminders)/10)):
			make_embed()

		if not pages:
			await ctx.send(f"This server does not have any recurring messages.")
			return

		c = DEFAULT_CONTROLS if len(pages) > 1 else {"\N{CROSS MARK}": close_menu}

		await menu(ctx, pages, c)

	@commands.is_owner()
	@recurring.group(autohelp=False)
	async def restart(self, ctx: commands.Context):
		"""Restart the internal task loop."""
		self.loop.restart()
		await ctx.tick()

	@tasks.loop(minutes=1.0)
	async def loop(self):
		try:
			# timezones are funny, so let's not deal with them!
			today: datetime = datetime.utcnow()
			today_date: date = today.date()
			current_time: time = today.timetz()

			guilds = await self.config.all_guilds()

			for guild_id in guilds.keys():
				guild: discord.Guild = self.bot.get_guild(guild_id)

				if(guild == None):
					continue

				async with self.config.guild(guild).reminders() as guild_reminders:
					guild_reminders: list[dict]
					rem_list: list[int] = [] # remie list...

					for idx, reminder in enumerate(guild_reminders):
						try:
							reminder_last_sent = date.fromisoformat(reminder["last_sent"])
							reminder_time = time.fromisoformat(reminder["time"])
						except Exception as e:
							log.exception(e)
							continue

						# Check whether we already sent that reminder today or not.
						if(reminder_last_sent >= today_date):
							continue

						# Check whether it's time to send that reminder or not.
						if(reminder_time > current_time):
							continue

						channel: discord.TextChannel = guild.get_channel(reminder["channel_id"])

						if(channel == None):
							rem_list.append(idx)
							continue

						await channel.send(reminder["message"])
						reminder["last_sent"] = today_date.isoformat()

					# Remove invalid reminders (for when the specific channel gets deleted)
					for idx in rem_list:
						guild_reminders.pop(idx)
						

		except Exception as e:
			log.exception(e)

	@loop.before_loop
	async def before_loop(self):
		await self.bot.wait_until_ready()