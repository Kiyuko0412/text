import discord
from discord.ext import commands
from discord.ui import View, Button, Select
import sqlite3
import asyncio
import json

# 設定檔
with open('config.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)

class MyBot(commands.Bot):
    def __init__(self):
        # 權限
        its = discord.Intents.all()
        super().__init__(command_prefix="=", intents=its)

    async def on_ready(self):
        print(f">> 機器人已上線：{self.user} <<")

bot = MyBot()

class ConfirmBtn(View):
    def __init__(self, uid):
        super().__init__(timeout=30)
        self.val = None
        self.uid = uid

    async def interaction_check(self, itn: discord.Interaction) -> bool:
        # 檢查是否為本人操作
        if itn.user.id != self.uid:
            await itn.response.send_message("這不是給你的按鈕！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="確認", style=discord.ButtonStyle.danger)
    async def ok(self, itn: discord.Interaction, btn: Button):
        self.val = True
        self.stop()
        await itn.response.defer()

    @discord.ui.button(label="取消", style=discord.ButtonStyle.grey)
    async def no(self, itn: discord.Interaction, btn: Button):
        self.val = False
        self.stop()
        await itn.response.defer()

# 資料庫
def conn_prog():
    return sqlite3.connect('progress.db')

def conn_data():
    return sqlite3.connect('data.db')

# 抓資料
def get_char_img(sid, name, emo):
    conn = conn_data()
    cur = conn.cursor()
    # 抓圖片網址
    sql = '''
        SELECT ci.url FROM character_images ci
        JOIN characters c ON ci.character_id = c.id
        WHERE c.story_id = ? AND c.name = ? AND ci.emotion = ?
    '''
    cur.execute(sql, (sid, name, emo))
    res = cur.fetchone()
    if res:
        conn.close()
        return res[0]
    
    # 找不到就用預設
    cur.execute(sql, (sid, name, "預設"))
    res = cur.fetchone()
    conn.close()
    if res:
        return res[0]
    
    return "https://cdn.discordapp.com/attachments/1218955308777603113/1414980855025369110/image.png?ex=68c18b1c&is=68c0399c&hm=e25c2be92a8d01020ea09a1721327262edea75487581564057cfdd86094bfeb6&"

def get_bg_img(sid, img_name):
    conn = conn_data()
    cur = conn.cursor()
    cur.execute("SELECT url FROM background_images WHERE story_id = ? AND name = ?", (sid, img_name))
    res = cur.fetchone()
    conn.close()
    return res[0] if res else None
    
def get_story(sid):
    conn = conn_data()
    cur = conn.cursor()
    cur.execute("SELECT name, file_path, start_scene FROM stories WHERE id = ?", (sid,))
    res = cur.fetchone()
    conn.close()
    return res if res else (None, None, None)

# 進度儲存 
def get_prog(uid, sid):
    conn = conn_prog()
    cur = conn.cursor()
    cur.execute("SELECT scene FROM progress WHERE user_id = ? AND story_id = ?", (uid, sid))
    res = cur.fetchone()
    conn.close()
    if res:
        return res[0]
    else:
        # 沒進度的話
        _, _, start = get_story(sid)
        return start if start else 'scene1'

def save_prog(uid, sid, sn):
    conn = conn_prog()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO progress (user_id, story_id, scene) VALUES (?, ?, ?)", (uid, sid, sn))
    conn.commit()
    conn.close()

def init_db():
    conn = conn_prog()
    cur = conn.cursor()
    # 初始進度表
    cur.execute("DROP TABLE IF EXISTS progress")
    cur.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER NOT NULL,
            story_id INTEGER NOT NULL,
            scene TEXT,
            PRIMARY KEY (user_id, story_id)
        )
    ''')
    conn.commit()
    conn.close()

# 拆字部分
def parse_txt(path, sn):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    data = {'lines': [], 'choices': [], 'imgs': []}
    cur_sn = None
    is_opt = False
    cur_img = None

    for l in lines:
        l = l.strip()
        if l.startswith('[') and l.endswith(']'):
            cur_sn = l[1:-1]
            is_opt = False
            cur_img = None
        elif cur_sn == sn:
            if l.startswith('<') and l.endswith('>'):
                cur_img = l[1:-1]
                data['imgs'].append(cur_img)
            elif l.startswith('提問'):
                is_opt = True
            elif is_opt and '->' in l:
                txt, target = l.split('->')
                desc = txt.split(':', 1)[-1].strip()
                target = target.strip().strip('[]')
                data['choices'].append(f"{desc} -> {target}")
            elif ':' in l:
                try:
                    if '{' in l and '}' in l:
                        msg, emo = l.split('{')
                        emo = emo.rstrip('}')
                    else:
                        msg = l
                        emo = "預設"

                    data['lines'].append((msg.strip(), emo.strip(), cur_img))
                except:
                    pass

    return data

# main
async def play(ctx, sid, sn):
    name, path, _ = get_story(sid)
    if not name:
        await ctx.send("找不到這個故事。")
        return

    r_path = f"story/{path}"
    data = parse_txt(r_path, sn)
    lines = data['lines']
    opts = data['choices']

    if not lines:
        await ctx.send("劇情結束或未找到該場景。")
        return

    emb = discord.Embed(title=name, description="", color=0x00ff00)
    emb.set_footer(text=f"章節: {sn}")
    v = View(timeout=None)

    cur_idx = 0

    # 選項回傳
    async def on_select(itn_sel):
        target_sn = itn_sel.data['values'][0]
        await itn_sel.message.delete()
        try:
            save_prog(ctx.author.id, sid, target_sn)
            await play_itn(itn_sel, sid, target_sn)
        except Exception as err:
            print(err)

    # 下一句按鈕
    async def next_msg(itn):
        nonlocal cur_idx
        cur_idx += 1
        
        if cur_idx < len(lines):
            line, emo, img_name = lines[cur_idx]
            role, msg = line.split(':', 1)
            role = role.strip()
            msg = msg.strip()

            url = get_char_img(sid, role, emo)
            emb.set_thumbnail(url=url)
            emb.description = f"**{role}**\n\n{msg}"

            if img_name:
                bg = get_bg_img(sid, img_name)
                if bg: emb.set_image(url=bg)
            else:
                emb.set_image(url=None)

            await itn.response.edit_message(embed=emb, view=v)
        else:
            v.clear_items()
            if opts:
                items = [discord.SelectOption(label=o.split('->')[0].strip(), value=o.split('->')[1].strip()) for o in opts]
                sel = Select(placeholder="你的選擇是...", options=items)
                sel.callback = on_select
                v.add_item(sel)
            await itn.response.edit_message(embed=emb, view=v)

    # 快速閱讀
    async def quick_read(itn):
        chk = ConfirmBtn(itn.user.id)
        await itn.response.send_message("要跳到結尾嗎？", view=chk, ephemeral=True)
        await chk.wait()

        if chk.val:
            nonlocal cur_idx
            cur_idx = len(lines) - 1
            
            line, emo, img_name = lines[cur_idx]
            role, msg = line.split(':', 1)
            role = role.strip()
            msg = msg.strip()

            url = get_char_img(sid, role, emo)
            emb.set_thumbnail(url=url)
            emb.description = f"**{role}**\n\n{msg}"
            emb.set_footer(text=f"章節: {sn} (快進)")

            if img_name:
                bg = get_bg_img(sid, img_name)
                if bg: emb.set_image(url=bg)
            else:
                emb.set_image(url=None)
            
            final_v = View(timeout=None)
            if opts:
                items = [discord.SelectOption(label=o.split('->')[0].strip(), value=o.split('->')[1].strip()) for o in opts]
                sel = Select(placeholder="你的選擇是...", options=items)
                sel.callback = on_select
                final_v.add_item(sel)
            
            await itn.message.edit(embed=emb, view=final_v)
            try:
                await itn.delete_original_response()
            except:
                pass

    btn_next = Button(label="下一句", style=discord.ButtonStyle.primary)
    btn_next.callback = next_msg
    v.add_item(btn_next)

    btn_fast = Button(label="快速閱讀", style=discord.ButtonStyle.secondary)
    btn_fast.callback = quick_read
    v.add_item(btn_fast)

    # 初始畫面
    line, emo, img_name = lines[cur_idx]
    role, msg = line.split(':', 1)
    url = get_char_img(sid, role.strip(), emo)
    emb.set_thumbnail(url=url)
    emb.description = f"**{role.strip()}**\n\n{msg.strip()}"

    if img_name:
        bg = get_bg_img(sid, img_name)
        if bg: emb.set_image(url=bg)

    await ctx.send(embed=emb, view=v)

# Interaction用
async def play_itn(itn_init, sid, sn):
    name, path, _ = get_story(sid)
    if not name:
        await itn_init.response.send_message("找不到這個故事。", ephemeral=True)
        return

    r_path = f"story/{path}"
    data = parse_txt(r_path, sn)
    lines = data['lines']
    opts = data['choices']

    if not lines:
        await itn_init.response.send_message("劇情結束或未找到該場景。", ephemeral=True)
        return

    emb = discord.Embed(title=name, description="", color=0x00ff00)
    emb.set_footer(text=f"章節: {sn}")
    v = View(timeout=None)

    cur_idx = 0

    async def on_select(itn_sel):
        target_sn = itn_sel.data['values'][0]
        await itn_sel.message.delete()
        try:
            save_prog(itn_init.user.id, sid, target_sn)
            await play_itn(itn_sel, sid, target_sn)
        except Exception as err:
            print(err)

    async def next_msg(itn):
        nonlocal cur_idx
        cur_idx += 1
        
        if cur_idx < len(lines):
            line, emo, img_name = lines[cur_idx]
            role, msg = line.split(':', 1)
            url = get_char_img(sid, role.strip(), emo)
            emb.set_thumbnail(url=url)
            emb.description = f"**{role.strip()}**\n\n{msg.strip()}"
            
            if img_name:
                bg = get_bg_img(sid, img_name)
                if bg: emb.set_image(url=bg)
            else:
                emb.set_image(url=None)

            await itn.response.edit_message(embed=emb, view=v)
        else:
            v.clear_items()
            if opts:
                items = [discord.SelectOption(label=o.split('->')[0].strip(), value=o.split('->')[1].strip()) for o in opts]
                sel = Select(placeholder="你的選擇是...", options=items)
                sel.callback = on_select
                v.add_item(sel)
            await itn.response.edit_message(embed=emb, view=v)

    async def quick_read(itn):
        chk = ConfirmBtn(itn.user.id)
        await itn.response.send_message("要跳到結尾嗎？", view=chk, ephemeral=True)
        await chk.wait()

        if chk.val:
            nonlocal cur_idx
            cur_idx = len(lines) - 1
            
            line, emo, img_name = lines[cur_idx]
            role, msg = line.split(':', 1)
            url = get_char_img(sid, role.strip(), emo)
            emb.set_thumbnail(url=url)
            emb.description = f"**{role.strip()}**\n\n{msg.strip()}"
            emb.set_footer(text=f"章節: {sn} (快進)")

            if img_name:
                bg = get_bg_img(sid, img_name)
                if bg: emb.set_image(url=bg)
            else:
                emb.set_image(url=None)
            
            final_v = View(timeout=None)
            if opts:
                items = [discord.SelectOption(label=o.split('->')[0].strip(), value=o.split('->')[1].strip()) for o in opts]
                sel = Select(placeholder="你的選擇是...", options=items)
                sel.callback = on_select
                final_v.add_item(sel)
            
            await itn.message.edit(embed=emb, view=final_v)
            try:
                await itn.delete_original_response()
            except:
                pass

    btn_next = Button(label="下一句", style=discord.ButtonStyle.primary)
    btn_next.callback = next_msg
    v.add_item(btn_next)

    btn_fast = Button(label="快速閱讀", style=discord.ButtonStyle.secondary)
    btn_fast.callback = quick_read
    v.add_item(btn_fast)
    
    line, emo, img_name = lines[cur_idx]
    role, msg = line.split(':', 1)
    url = get_char_img(sid, role.strip(), emo)
    emb.set_thumbnail(url=url)
    emb.description = f"**{role.strip()}**\n\n{msg.strip()}"

    if img_name:
        bg = get_bg_img(sid, img_name)
        if bg: emb.set_image(url=bg)
    
    await itn_init.response.send_message(embed=emb, view=v)

#測試
@bot.command()
async def test(ctx, sid: int, sn: str):
    try:
        await play(ctx, sid, sn)
    except Exception as e:
        await ctx.send(e)

#開始頁面
@bot.command()
async def start(ctx):
    await ctx.message.delete()

    conn = conn_data()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM stories")
    all_stories = cur.fetchall()
    conn.close()

    if not all_stories:
        await ctx.send("沒故事。")
        return

    items = [discord.SelectOption(label=n, value=str(i)) for i, n in all_stories]
    sel = Select(placeholder="選擇故事...", options=items)

    async def pick_story(itn):
        sid = int(itn.data['values'][0])
        name, _, start_sn = get_story(sid)

        if not start_sn:
            await itn.response.edit_message(content="故事沒設起始點。", view=None)
            return

        emb = discord.Embed(title=f"故事: {name}", description="開始遊戲？", color=0x00ff00)
        v = View()

        btn_new = Button(label="開新遊戲", style=discord.ButtonStyle.primary)
        async def go_new(itn_new):
            await itn_new.response.defer()
            await itn_new.message.delete()
            save_prog(ctx.author.id, sid, start_sn)
            await play(ctx, sid, start_sn)

        btn_new.callback = go_new
        v.add_item(btn_new)

        btn_cont = Button(label="繼續遊戲", style=discord.ButtonStyle.secondary)
        async def go_cont(itn_cont):
            await itn_cont.response.defer()
            await itn_cont.message.delete()
            sn = get_prog(ctx.author.id, sid)
            await play(ctx, sid, sn)
        
        btn_cont.callback = go_cont
        v.add_item(btn_cont)

        await itn.response.edit_message(embed=emb, view=v)

    sel.callback = pick_story

    emb = discord.Embed(title="歡迎！", description="請選擇一個故事。", color=0x00ff00)
    v = View()
    v.add_item(sel)
    await ctx.send(embed=emb, view=v)

async def main():
    async with bot:
        await bot.start(cfg['token'])

if __name__ == "__main__":
    asyncio.run(main())
