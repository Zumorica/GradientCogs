from .recurringmessages import RecurringMessages

__red_end_user_data_statement__ = ''

def setup(bot):
	bot.add_cog(RecurringMessages(bot))
