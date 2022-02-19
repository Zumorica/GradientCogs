# MIT License

# Copyright (c) 2018 Flame442

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Forked from https://github.com/Flame442/FlameCogs

from typing import List
import discord
from redbot.core import bank
from redbot.core import commands
from redbot.core import Config
from redbot.core.utils.chat_formatting import pagify, box
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS, close_menu
from prettytable import PrettyTable
from math import ceil
import aiohttp, prettytable


class Stocks(commands.Cog):
	"""Buy and sell stocks with bot currency."""
	def __init__(self, bot):
		self.bot = bot
		self.config = Config.get_conf(self, identifier=8712341782873811)
		self.config.register_guild(conversion = 10)
		self.config.register_member(stocks = {})

	@commands.guild_only()
	@commands.group(aliases=['stock', 'stonks', 'stonk'])
	async def stocks(self, ctx: commands.Context):
		"""Group command for stocks."""
		pass

	@stocks.group()
	@commands.guildowner_or_permissions(administrator=True)
	async def set(self, ctx: commands.Context):
		"""Group command for changing stock settings."""
		pass

	@set.command()
	async def conversion(self, ctx: commands.Context, rate: int):
		"""Sets the current USD -> Currency conversion rate. Must be greater than zero."""
		if(rate <= 0):
			await ctx.react_quietly(reaction="❌")
			await ctx.send_help()
			return

		await self.config.guild(ctx.guild).conversion.set(rate)
		await ctx.tick()


	@stocks.command()
	async def conversion(self, ctx: commands.Context):
		"""Returns the current USD -> Currency conversion rate."""
		conversion = await self.config.guild(ctx.guild).conversion()
		currency = await bank.get_currency_name(ctx.guild)
		await ctx.send(f'Current conversion rate: 1 USD = {conversion} {currency}')

	@stocks.command()
	async def buy(self, ctx: commands.Context, name: str, shares: int):
		"""
		Buy stocks.

		Enter the ticker symbol for the stock.
		"""
		plural = 's' if shares != 1 else ''
		currency = await bank.get_currency_name(ctx.guild)
		if shares < 1:
			await ctx.send('You cannot buy less than one share.')
			return
		name = name.upper()
		try:
			stock_data = await self.get_stock_data(ctx, [name])
		except ValueError as e:
			return await ctx.send(e)
		if name not in stock_data:
			await ctx.send(f'I couldn\'t find any data for the stock {name}. Please try another stock.')
			return
		price = stock_data[name]['price']
		try:
			bal = await bank.withdraw_credits(ctx.author, shares * price)
		except ValueError:
			bal = await bank.get_balance(ctx.author)
			await ctx.send(
				f'You cannot afford {shares} share{plural} of {name}. '
				f'It would cost {price * shares} {currency} ({price} {currency} each). '
				f'You only have {bal} {currency}.'
			)
			return
		async with self.config.member(ctx.author).stocks() as user_stocks:
			if name in user_stocks:
				user_stocks[name]['count'] += shares
			else:
				user_stocks[name] = {'count': shares}
		await ctx.send(
			f'You purchased {shares} share{plural} of {name} for {price * shares} {currency} '
			f'({price} {currency} each).\nYou now have {bal} {currency}.'
		)

	@stocks.command()
	async def sell(self, ctx: commands.Context, name: str, shares: int):
		"""
		Sell stocks.

		Enter the ticker symbol for the stock.
		"""
		plural = 's' if shares != 1 else ''
		if shares < 1:
			await ctx.send('You cannot sell less than one share.')
			return
		name = name.upper()
		try:
			stock_data = await self.get_stock_data(ctx, [name])
		except ValueError as e:
			return await ctx.send(e)
		if name not in stock_data:
			await ctx.send(f'I couldn\'t find any data for the stock {name}. Please try another stock.')
			return
		price = stock_data[name]['price']
		async with self.config.member(ctx.author).stocks() as user_stocks:
			if name not in user_stocks:
				await ctx.send(f'You do not have any shares of {name}.')
				return
			if shares > user_stocks[name]['count']:
				await ctx.send(
					f'You do not have enough shares of {name}. '
					f'You only have {user_stocks[name]["count"]} share{plural}.'
				)
				return
			user_stocks[name]['count'] -= shares
			if user_stocks[name]['count'] == 0:
				del user_stocks[name]
		bal = await bank.deposit_credits(ctx.author, shares * price)
		currency = await bank.get_currency_name(ctx.guild)
		await ctx.send(
			f'You sold {shares} share{plural} of {name} for {price * shares} {currency} '
			f'({price} {currency} each).\nYou now have {bal} {currency}.'
		)

	@stocks.command()
	async def list(self, ctx: commands.Context, user: discord.Member = None):
		"""List someone's stocks."""

		if(user == None):
			user = ctx.author

		user_stocks = await self.config.member(user).stocks()

		if(len(user_stocks.items()) == 0):
			await ctx.send(f"{user.name} does not have any stocks.")
			return

		try:
			stock_data = await self.get_stock_data(ctx, user_stocks.keys())
		except ValueError as e:
			return await ctx.send(e)

		embed_requested = await ctx.embed_requested()
		base_embed = discord.Embed()
		base_embed.set_author(name=f"{user.name} - Stocks", icon_url=user.avatar_url)
		base_table = PrettyTable(field_names=["#", "Name", "Shares", "Value", "Price"])
		base_table.set_style(prettytable.PLAIN_COLUMNS)
		base_table.right_padding_width = 2
		base_table.align = "l"
		base_table.align["Value"] = base_table.align["Shares"] = base_table.align["Price"] = "r"

		temp_table = base_table.copy()

		pages = []

		def make_embed():
			nonlocal temp_table, pages
			msg = temp_table.get_string()

			if(embed_requested):
				embed = base_embed.copy()
				embed.description = box(msg, lang="md")
				embed.set_footer(text=f"Page {len(pages)+1}/{ceil(len(user_stocks)/10)}")
				pages.append(embed)
			else:
				pages.append(box(msg, lang="md"))

			temp_table = base_table.copy()

		for idx, stock in enumerate(user_stocks, start=1):
			if stock in stock_data:
				price = stock_data[stock]["price"]
			else:
				price = 0

			count = user_stocks[stock]["count"]
			temp_table.add_row([f"{idx}.", stock, count, price * count, price])
			
			if(idx % 10 == 0):
				make_embed()

		if(len(pages) != ceil(len(user_stocks)/10)):
			make_embed()

		if not pages:
			await ctx.send(f"{user.name} does not have any stocks.")
			return

		c = DEFAULT_CONTROLS if len(pages) > 1 else {"\N{CROSS MARK}": close_menu}

		await menu(ctx, pages, c)

	@stocks.command()
	async def leaderboard(self, ctx: commands.Context):
		"""Show a leaderboard of total stock value by user."""
		# TODO: convert to buttons whenever I get around to 3.5 support
		raw = await self.config.all_members()

		if(ctx.guild.id not in raw):
			await ctx.send("Nobody owns any stocks yet!")
			return

		raw = raw[ctx.guild.id]		
		stocks = set()

		for uid, data in raw.items():
			stocks = stocks.union(set(data['stocks'].keys()))

		try:
			stock_data = await self.get_stock_data(ctx, list(stocks))
		except ValueError as e:
			return await ctx.send(e)

		processed = []

		for uid, data in raw.items():
			total_value = 0
			total_shares = 0
			for ticker, stock in data['stocks'].items():
				if ticker not in stock_data:
					continue
				total_value += stock['count'] * stock_data[ticker]['price']
				total_shares += stock['count']
			if not total_shares:
				continue
			processed.append((uid, total_value, total_shares))
		
		processed.sort(key=lambda a: a[1], reverse=True)
		
		embed_requested = await ctx.embed_requested()
		base_embed = discord.Embed()
		base_embed.set_author(name=f"{ctx.guild.name} - Stocks", icon_url=ctx.guild.icon_url)
		base_table = PrettyTable(field_names=["#", "Name", "Value", "Shares"])
		base_table.set_style(prettytable.PLAIN_COLUMNS)
		base_table.right_padding_width = 2
		base_table.align = "l"
		base_table.align["Value"] = base_table.align["Shares"] = "r"

		temp_table = base_table.copy()

		pages = []

		def make_embed():
			nonlocal temp_table, pages
			msg = temp_table.get_string()

			if(embed_requested):
				embed = base_embed.copy()
				embed.description = box(msg, lang="md")
				embed.set_footer(text=f"Page {len(pages)+1}/{ceil(len(processed)/10)}")
				pages.append(embed)
			else:
				pages.append(box(msg, lang="md"))

			temp_table = base_table.copy()

		for idx, data in enumerate(processed, start=1):
			uid, total_value, total_shares = data
			user = self.bot.get_user(uid)
			if user:
				user = user.name
			else:
				user = f'<Unknown user `{uid}`>'

			temp_table.add_row([f"{idx}.", user, total_value, total_shares])

			if(idx % 10 == 0):
				make_embed()

		if(len(pages) != ceil(len(processed)/10)):
			make_embed()

		if not pages:
			await ctx.send('Nobody owns any stocks yet!')
			return

		c = DEFAULT_CONTROLS if len(pages) > 1 else {"\N{CROSS MARK}": close_menu}

		await menu(ctx, pages, c)

	@stocks.command()
	async def price(self, ctx: commands.Context, name: str):
		"""
		View the price of a stock.

		Enter the ticker symbol for the stock.
		"""
		name = name.upper()
		try:
			stock_data = await self.get_stock_data(ctx, [name])
		except ValueError as e:
			return await ctx.send(e)
		if name not in stock_data:
			await ctx.send(f'I couldn\'t find any data for the stock {name}. Please try another stock.')
			return
		price = stock_data[name]['price']
		real = stock_data[name]['realPrice']
		change = stock_data[name]['change']
		currency = await bank.get_currency_name(ctx.guild)

		if(change == 0):
			emoji = ""
		elif(change < 0):
			emoji = "📉"
		elif(change > 0):
			emoji = "📈"

		await ctx.send(f'**{name}:** {price} {currency} per share (${"%.3f" % real} <{emoji} {"%.2f" % change} %>).')

	async def get_stock_data(self, ctx: commands.Context, stocks: List[str]):
		"""
		Returns a dict mapping stock symbols to a dict of their converted price and the total shares of that stock.

		This function is designed to contain all of the API code in order to avoid having to mangle multiple parts
		of the code in the event of an API change.
		"""
		api_url = 'https://query1.finance.yahoo.com/v7/finance/quote?lang=en-US&region=US&corsDomain=finance.yahoo.com'
		stocks = ','.join(stocks)

		if not stocks:
			return []

		api_url += "&symbols=" + stocks
		api_url += "&fields=symbol,regularMarketPrice,regularMarketChangePercent"

		headers = {'Accept': 'application/json'}
		async with aiohttp.ClientSession() as session:
			async with session.get(api_url, headers=headers) as r:
				try:
					r = await r.json()
				except aiohttp.client_exceptions.ContentTypeError:
					#This might happen when being rate limited, but IDK for sure...
					raise ValueError('Could not get stock data. Are we being rate-limited?')
		
		r = r["quoteResponse"]["result"]

		conversion = await self.config.guild(ctx.guild).conversion()

		stock = {
			x["symbol"]: {
				"realPrice" : x['regularMarketPrice'],
				"change" : x["regularMarketChangePercent"],
				"price": max(1, round(x['regularMarketPrice'] * conversion))
			}

			for x in r if "regularMarketPrice" in x and x["regularMarketPrice"] is not None
		}

		return stock