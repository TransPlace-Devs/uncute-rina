import discord # It's dangerous to go alone! Take this. /ref
from discord import app_commands # v2.0, use slash commands
from discord.ext import commands # required for client bot making
from utils import *
from datetime import datetime, timedelta
from time import mktime # for unix time code
import matplotlib.pyplot as plt
import pandas as pd

import pymongo # for online database
from pymongo import MongoClient
mongoURI = open("mongo.txt","r").read()
cluster = MongoClient(mongoURI)
RinaDB = cluster["Rina"]

class MemberData(commands.Cog):
    async def addToData(self, member, type):
        collection = RinaDB["data"]
        query = {"guild_id": member.guild.id}
        data = collection.find(query)
        try:
            data = data[0]
        except IndexError:
            collection.insert_one(query)
            data = collection.find(query)[0]
        try:
            #see if this user already has data, if so, add a new joining time to the list
            data[type][str(member.id)].append(mktime(datetime.utcnow().timetuple()))
        except IndexError:
            data[type][str(member.id)] = [mktime(datetime.utcnow().timetuple())]
        except KeyError:
            data[type] = {}
            data[type][str(member.id)] = [mktime(datetime.utcnow().timetuple())]
        collection.update_one(query, {"$set":{f"{type}.{member.id}":data[type][str(member.id)]}}, upsert=True)
        debug(f"Successfully added new data for {member.name} to {repr(type)}",color="blue")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await self.addToData(member,"joined")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.addToData(member,"left")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        role = discord.utils.find(lambda r: r.name == 'Verified', before.guild.roles)
        if role not in before.roles and role in after.roles:
            await self.addToData(after,"verified")

    @app_commands.command(name="getmemberdata",description="See joined, left, and recently verified users in x days")
    @app_commands.describe(period="Get data from [period] days ago",
                           doubles="If someone joined twice, are they counted double? (y/n or 1/0)")
    async def getMemberData(self, itx: discord.Interaction, period: str, doubles: bool = False, hidden: bool = True):
        if not isStaff(itx):
            await itx.response.send_message("You don't have the right role to be able to execute this command! (sorrryyy)",ephemeral=True) #todo
            return
        try:
            period = float(period)
            if period <= 0:
                await itx.response.send_message("Your period (data in the past [x] days) has to be above 0!",ephemeral=True)
                return
        except ValueError:
            await itx.response.send_message("Your period has to be an integer for the amount of days that have passed",ephemeral=True)
            return
        accuracy = period*2400 #divide graph into 36 sections
        period *= 86400 # days to seconds
        # Get a list of people (in this server) that joined at certain times. Maybe round these to a certain factor (don't overstress the x-axis)
        # These certain times are in a period of "now" and "[period] seconds ago"
        totals = []
        results = {}
        warning = ""
        currentTime = mktime(datetime.utcnow().timetuple()) #  todo: globalize the time # maybe fixed with .utcnow() ?
        minTime = int((currentTime-period)/accuracy)*accuracy
        maxTime = int(currentTime/accuracy)*accuracy

        collection = RinaDB["data"]
        query = {"guild_id": itx.guild_id}
        data = collection.find(query)
        try:
            data = data[0]
        except IndexError:
            await itx.response.send_message("Not enough data is configured to do this action! Please hope someone joins sometime soon lol",ephemeral=True)
            return

        await itx.response.defer(ephemeral=hidden)
        for y in data:
            if type(data[y]) is not dict: continue
            column = []
            results[y] = {}
            for member in data[y]:
                for time in data[y][member]:
                    #if the current time minus the amount of seconds in every day in the period since now, is still older than more recent joins, append it
                    if currentTime-period < time:
                        column.append(time)
                        if not doubles:
                            break
            totals.append(len(column))
            for time in range(len(column)):
                column[time] = int(column[time]/accuracy)*accuracy
                if column[time] in results[y]:
                    results[y][column[time]] += 1
                else:
                    results[y][column[time]] = 1
            if len(column) == 0:
                warning += f"\nThere were no '{y}' users found for this time period."
                debug(warning[1:],color="light purple")
            else:
                timeList = sorted(column)
                if minTime > timeList[0]:
                    minTime = timeList[0]
                if maxTime < timeList[-1]:
                    maxTime = timeList[-1]
        minTimeDB = minTime
        for y in data:
            if type(data[y]) is not dict: continue
            minTime = minTimeDB
            while minTime <= maxTime:
                if minTime not in results[y]:
                    results[y][minTime] = 0
                minTime += accuracy
        result = {}
        for i in results:
            result[i] = {}
            for j in sorted(results[i]):
                result[i][j]=results[i][j]
            results[i] = result[i]

        try:
            d = {
                "time": [i for i in results["joined"]],
                "joined":[results["joined"][i] for i in results["joined"]],
                "left":[results["left"][i] for i in results["left"]],
                "verified":[results["verified"][i] for i in results["verified"]]
            }
        except KeyError as ex:
            await itx.followup.send(f"{ex} did not have data, thus could not make the graph.")
            return
        df = pd.DataFrame(data=d)
        fig, (ax1) = plt.subplots(1,1)
        fig.suptitle(f"Member +/-/verif (r/g/b) in the past {period/86400} days")
        fig.tight_layout(pad=1.0)
        ax1.plot(df['time'], df["joined"], 'b')
        ax1.plot(df['time'], df["left"], 'r')
        ax1.plot(df['time'], df["verified"], 'g')
        if doubles:
            reText = "exc"
        else:
            reText = "inc"
        ax1.set_ylabel(f"# of members ({reText}. rejoins/-leaves/etc)")

        tickLoc = [i for i in df['time'][::3]]
        if period/86400 <= 1:
            tickDisp = [datetime.fromtimestamp(i).strftime('%H:%M') for i in tickLoc]
        else:
            tickDisp = [datetime.fromtimestamp(i).strftime('%Y-%m-%dT%H:%M') for i in tickLoc]

        # plt.xticks(tickLoc, tickDisp, rotation='vertical')
        # plt.setp(tickDisp, rotation=45, horizontalalignment='right')
        ax1.set_xticks(tickLoc,
                labels=tickDisp,
                horizontalalignment = 'right',
                minor=False,
                rotation=30)
        ax1.grid(visible=True, which='major', axis='both')
        fig.subplots_adjust(bottom=0.180, top=0.90, left=0.1, hspace=0.1)
        plt.savefig('userJoins.png')
        await itx.followup.send(f"In the past {period/86400} days, `{totals[0]}` members joined, `{totals[1]}` left, and `{totals[2]}` were verified. (with{'out'*(1-doubles)} doubles)"+warning,file=discord.File('userJoins.png') )


async def setup(client):
    # client.add_command(getMemberData)
    await client.add_cog(MemberData(client))
