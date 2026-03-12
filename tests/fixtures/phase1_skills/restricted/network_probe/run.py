from src.dynamic_os.contracts.skill_io import SkillOutput


async def run(ctx):
    await ctx.tools.search("permission probe")
    return SkillOutput(success=True)
