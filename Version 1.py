import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime
import random
import uuid
import requests
import aiohttp
from aiohttp import web # ADICIONADO PARA O RENDER
from supabase import create_client, Client
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import os
from dotenv import load_dotenv

# ==========================================
# CONFIGURACIONES Y CREDENCIALES (SEGURAS VIA .ENV)
# ==========================================
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    raise ValueError("❌ Faltan credenciales. Asegúrate de configurar tu archivo .env con DISCORD_TOKEN, SUPABASE_URL y SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)

bot_locked = False

# ==========================================
# SISTEMA DE KEEP-ALIVE PARA O RENDER (NOVO)
# ==========================================
async def handle_web(request):
    return web.Response(text="Bot SSA Guru está online e rodando no Render!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_web)
    runner = web.AppRunner(app)
    await runner.setup()
    # O Render passa a porta dinamicamente pela variável de ambiente PORT
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Servidor web fantasma rodando na porta {port} para o Render.")

# ==========================================
# OTIMIZAÇÃO: GESTÃO DE RECURSOS E CACHE (500MB RAM SAFE)
# ==========================================
IMAGE_WIDTH, IMAGE_HEIGHT = 1400, 2100 
CARD_W, CARD_H = 300, 450 

BASE_FIELD_IMAGE = None
CACHED_FONTS = {}
PLAYER_CARD_CACHE = {} 
MAX_CACHE_SIZE = 100 
HTTP_SESSION = None 

TACTICAL_COORDINATES = [
    {"group": "PO",  "pos": (700, 1800)},
    {"group": "DFC", "pos": (190, 1350)}, {"group": "DFC", "pos": (530, 1350)}, {"group": "DFC", "pos": (870, 1350)}, {"group": "DFC", "pos": (1210, 1350)},
    {"group": "MID", "pos": (275, 900)},  {"group": "MID", "pos": (700, 900)},  {"group": "MID", "pos": (1125, 900)},
    {"group": "DC",  "pos": (275, 450)},  {"group": "DC",  "pos": (700, 450)},  {"group": "DC",  "pos": (1125, 450)}
]

def get_pos_group(pos):
    pos = pos.upper()
    if pos in ["MC", "MCO", "MCD"]: return "MID"
    return pos

def get_renogare_font_cached(size):
    if size in CACHED_FONTS:
        return CACHED_FONTS[size]
    font_filename = "renogare.otf"
    try:
        font = ImageFont.truetype(font_filename, size)
        CACHED_FONTS[size] = font
        return font
    except OSError:
        return ImageFont.load_default()

def draw_base_field():
    width, height = IMAGE_WIDTH, IMAGE_HEIGHT
    field_img = Image.new("RGB", (width, height), color="#1A1A1A")
    draw = ImageDraw.Draw(field_img, "RGBA")

    for i in range(0, height, 85):
        if (i // 85) % 2 == 0: 
            draw.rectangle([0, i, width, i+85], fill="#2A2A2A")

    line_color = (255, 255, 255, 180)
    lw = 12 
    draw.rectangle([40, 40, width-40, height-40], outline=line_color, width=lw)
    draw.line([40, height//2, width-40, height//2], fill=line_color, width=lw)
    draw.ellipse([width//2 - 180, height//2 - 180, width//2 + 180, height//2 + 180], outline=line_color, width=lw)
    draw.rectangle([350, 40, width-350, 350], outline=line_color, width=lw)
    draw.rectangle([350, height-350, width-350, height-40], outline=line_color, width=lw)

    draw.rectangle([0, 0, width, 150], fill=(0, 0, 0, 220))
    draw.rectangle([0, height-120, width, height], fill=(0, 0, 0, 220))
    return field_img

async def fetch_player_image_async(session, player_id, card_url):
    if player_id in PLAYER_CARD_CACHE:
        img = PLAYER_CARD_CACHE.pop(player_id)
        PLAYER_CARD_CACHE[player_id] = img
        return img

    if not card_url:
        return None

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        async with session.get(card_url, headers=headers, timeout=8) as response:
            if response.status != 200:
                return None
            image_bytes = await response.read()
            
            def process_image():
                try:
                    p_img = Image.open(BytesIO(image_bytes)).convert("RGBA")
                    p_img = p_img.resize((CARD_W, CARD_H), Image.Resampling.LANCZOS)
                    
                    if len(PLAYER_CARD_CACHE) >= MAX_CACHE_SIZE:
                        oldest_key = next(iter(PLAYER_CARD_CACHE))
                        del PLAYER_CARD_CACHE[oldest_key]
                        
                    PLAYER_CARD_CACHE[player_id] = p_img
                    return p_img
                except Exception:
                    return None
            
            return await asyncio.to_thread(process_image)
    except Exception:
        return None

def compile_team_image_sync(filled_slots, club_name, club_sigla, money, overall_total, processed_cards_map):
    width, height = IMAGE_WIDTH, IMAGE_HEIGHT
    temp_img = BASE_FIELD_IMAGE.copy()
    draw = ImageDraw.Draw(temp_img, "RGBA")

    title_font = get_renogare_font_cached(60)
    metrics_font = get_renogare_font_cached(48)
    plus_font = get_renogare_font_cached(100)

    for i, slot in enumerate(TACTICAL_COORDINATES):
        cx, cy = slot["pos"]
        player = filled_slots[i]
        p_img = None
        
        if player:
            p_img = processed_cards_map.get(player["id"])

        if p_img:
            temp_img.paste(p_img, (int(cx - CARD_W//2), int(cy - CARD_H//2)), p_img)
        else:
            x1, y1 = int(cx - CARD_W//2), int(cy - CARD_H//2)
            x2, y2 = int(cx + CARD_W//2), int(cy + CARD_H//2)
            draw.rounded_rectangle([x1, y1, x2, y2], radius=20, fill=(30, 30, 30, 180), outline="#666666", width=5)
            draw.text((cx, cy), "+", font=plus_font, fill="#888888", anchor="mm")

    draw.text((width//2, 75), f"[{club_sigla}] {club_name.upper()}", font=title_font, fill="#f1c40f", anchor="mm")
    money_text = f"💰 ${money:,}"
    draw.text((40, height - 60), money_text, font=metrics_font, fill="white", anchor="lm")
    over_text = f"⭐ Over Total: {overall_total}"
    draw.text((width - 40, height - 60), over_text, font=metrics_font, fill="white", anchor="rm")
    
    buffer = BytesIO()
    temp_img.save(buffer, format='PNG', optimize=True)
    buffer.seek(0)
    return buffer

async def optimized_generate_pitch_image(xi_players, club_name, club_sigla, money, overall_total):
    filled_slots = [None] * 11
    used_ids = set()
    needed_images_tasks = []

    for i, slot in enumerate(TACTICAL_COORDINATES):
        found_player = None
        for player in xi_players:
            if player["id"] in used_ids: continue
            if get_pos_group(player.get("pos", "MC")) == slot["group"]:
                found_player = player
                filled_slots[i] = player
                used_ids.add(player["id"])
                break
        
        if found_player:
            task = fetch_player_image_async(HTTP_SESSION, found_player["id"], found_player.get("card"))
            needed_images_tasks.append((found_player["id"], task))

    ids_to_process, tasks = zip(*needed_images_tasks) if needed_images_tasks else ([], [])
    processed_results = await asyncio.gather(*tasks)
    
    processed_cards_map = {p_id: p_img for p_id, p_img in zip(ids_to_process, processed_results)}

    return await asyncio.to_thread(compile_team_image_sync, filled_slots, club_name, club_sigla, money, overall_total, processed_cards_map)

# ==========================================
# FUNCIONES AUXILIARES BASE DE DATOS
# ==========================================
async def db_get(doc_id: str):
    def fetch():
        response = supabase.table("jogadores").select("*").eq("id", doc_id).execute()
        return response.data[0] if response.data else None
    return await asyncio.to_thread(fetch)

async def db_upsert(doc_id: str, data: dict):
    def push():
        supabase.table("jogadores").upsert({"id": doc_id, "data": data}).execute()
    await asyncio.to_thread(push)

async def db_delete(doc_id: str):
    def remove():
        supabase.table("jogadores").delete().eq("id", doc_id).execute()
    await asyncio.to_thread(remove)

async def get_all_players():
    def fetch_all():
        response = supabase.table("jogadores").select("*").like("id", "player_%").execute()
        return response.data
    return await asyncio.to_thread(fetch_all)

async def get_all_users():
    def fetch_all():
        response = supabase.table("jogadores").select("*").like("id", "user_%").execute()
        return response.data
    return await asyncio.to_thread(fetch_all)

async def get_user_profile(user: discord.abc.User):
    doc_id = f"user_{user.id}"
    user_data = await db_get(doc_id)
    if not user_data:
        default_data = {
            "money": 0, "club_name": f"Club de {user.display_name}"[:30], "inventory": [],
            "starting_xi": [], "last_claim": 0, "last_sobre": 0,
            "wins": 0, "losses": 0, "captain": None
        }
        await db_upsert(doc_id, default_data)
        return default_data
    else:
        if str(user.id) in user_data["data"]["club_name"]:
            user_data["data"]["club_name"] = f"Club de {user.display_name}"[:30]
            await db_upsert(doc_id, user_data["data"])
        return user_data["data"]

async def save_user_profile(user_id: int, data: dict):
    await db_upsert(f"user_{user_id}", data)

def calculate_price(overall: int) -> int:
    base_price = 2000000
    multiplier = 1.15
    return int(base_price * (multiplier ** (overall - 80)))

def get_random_player_name(xi_list, pos_groups):
    players = [p['name'] for p in xi_list if get_pos_group(p.get('pos', 'MC')) in pos_groups]
    if not players: 
        players = [p['name'] for p in xi_list]
    return random.choice(players).split()[-1] if players else "El jugador"

# ==========================================
# CHECKS Y CLASES UI
# ==========================================
def is_not_locked():
    async def predicate(interaction: discord.Interaction):
        if bot_locked and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🛠️ **El bot está en mantenimiento.** Vuelve más tarde.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

class PaginatorView(discord.ui.View):
    def __init__(self, pages):
        super().__init__(timeout=60)
        self.pages = pages
        self.current_page = 0

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.primary, custom_id="prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Siguiente", style=discord.ButtonStyle.primary, custom_id="next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)
        else:
            await interaction.response.defer()

class BuyView(discord.ui.View):
    def __init__(self, user, matches):
        super().__init__(timeout=180)
        self.user = user
        self.matches = matches
        self.current_index = 0

    async def update_view(self, interaction: discord.Interaction):
        player = self.matches[self.current_index]
        precio = calculate_price(player["over"])
        
        self.children[0].disabled = (self.current_index == 0)
        self.children[1].label = f"Comprar (${precio:,})"
        self.children[1].disabled = False
        self.children[1].style = discord.ButtonStyle.success
        self.children[2].disabled = (self.current_index == len(self.matches) - 1)
        
        embed = discord.Embed(title="🛒 Mercado de Fichajes", description=f"Buscando: **{player['name']}**", color=discord.Color.blue())
        embed.add_field(name="Posición", value=player["pos"], inline=True)
        embed.add_field(name="Overall", value=f"⭐ {player['over']}", inline=True)
        embed.add_field(name="Valor de Mercado", value=f"💰 **${precio:,}**", inline=False)
        if player.get("card"):
            embed.set_image(url=player["card"])
            
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id: return await interaction.response.defer()
        self.current_index -= 1
        await self.update_view(interaction)

    @discord.ui.button(label="Comprar", style=discord.ButtonStyle.success)
    async def buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id: return await interaction.response.defer()
        
        player = self.matches[self.current_index]
        precio = calculate_price(player["over"])
        user_profile = await get_user_profile(self.user)
        
        if any(p["id"] == player["id"] for p in user_profile["inventory"]):
            return await interaction.response.send_message("❌ Ya tienes a este jugador en tu club.", ephemeral=True)
            
        if user_profile["money"] < precio:
            return await interaction.response.send_message(f"💸 **Fondos insuficientes.** Necesitas ${precio:,} para comprar a {player['name']}.", ephemeral=True)
            
        user_profile["money"] -= precio
        user_profile["inventory"].append(player)
        await save_user_profile(interaction.user.id, user_profile)
        
        self.children[1].disabled = True
        self.children[1].label = "Comprado"
        self.children[1].style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"✅ **¡Fichaje Exitoso!** Has contratado a **{player['name']}** por **${precio:,}**.", ephemeral=True)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id: return await interaction.response.defer()
        self.current_index += 1
        await self.update_view(interaction)

class ClaimView(discord.ui.View):
    def __init__(self, user, player, precio):
        super().__init__(timeout=60)
        self.user = user
        self.player = player
        self.precio_venta = int(precio * 0.5)
        self.processed = False

    @discord.ui.button(label="Ficar (Añadir al Club)", style=discord.ButtonStyle.success, emoji="✅")
    async def keep_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id or self.processed: return await interaction.response.defer()
        self.processed = True
        
        profile = await get_user_profile(self.user)
        if any(p["id"] == self.player["id"] for p in profile["inventory"]):
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.title = "❌ Ya posees a este jugador"
            embed.description = "El jugador ya estaba en tu inventario."
            self.disable_all()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            profile["inventory"].append(self.player)
            await save_user_profile(self.user.id, profile)
            
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.title = f"🎉 ¡{self.player['name']} Añadido al Club!"
            embed.description = f"✅ **El jugador ha sido guardado en tu inventario.**"
            self.disable_all()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Vender Jugador", style=discord.ButtonStyle.danger, emoji="💰")
    async def sell_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id or self.processed: return await interaction.response.defer()
        self.processed = True
        
        profile = await get_user_profile(self.user)
        profile["money"] += self.precio_venta
        await save_user_profile(self.user.id, profile)
        
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.gold()
        embed.title = f"💰 ¡{self.player['name']} Vendido!"
        embed.description = f"💸 **La directiva vendió al jugador por ${self.precio_venta:,}.**"
        self.disable_all()
        await interaction.response.edit_message(embed=embed, view=self)

    def disable_all(self):
        for child in self.children:
            child.disabled = True

class TeamView(discord.ui.View):
    def __init__(self, user):
        super().__init__(timeout=120)
        self.user = user

    @discord.ui.button(label="Auto Escalar (4-3-3)", style=discord.ButtonStyle.success, custom_id="auto_squad")
    async def auto_squad(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("No puedes gestionar este equipo.", ephemeral=True)
        
        await interaction.response.defer()
        
        user_profile = await get_user_profile(self.user)
        inventory = sorted(user_profile["inventory"], key=lambda x: x["over"], reverse=True)
        
        needs = {"PO": 1, "DFC": 4, "MID": 3, "DC": 3}
        new_xi = []
        used_ids = set()
        
        for pos_group, count in needs.items():
            added = 0
            for p in inventory:
                if p["id"] not in used_ids:
                    p_group = get_pos_group(p.get("pos", "MC"))
                    if p_group == pos_group and added < count:
                        new_xi.append(p)
                        used_ids.add(p["id"])
                        added += 1
                    
        user_profile["starting_xi"] = new_xi
        await save_user_profile(self.user.id, user_profile)
        
        sigla = user_profile['club_name'][:3].upper()
        money = user_profile['money']
        overall_total = sum(p["over"] for p in new_xi)
        
        image_bytes = await optimized_generate_pitch_image(new_xi, user_profile["club_name"], sigla, money, overall_total)
        file = discord.File(image_bytes, filename="pitch.png")
        
        embed = discord.Embed(title=f"🏟️ Prancheta Tática: {user_profile['club_name']}", color=discord.Color.dark_green())
        embed.add_field(name="Rating del Equipo (SOMA)", value=f"⭐ {overall_total}", inline=True)
        embed.add_field(name="Formación", value="4-3-3 (Dinámico)", inline=True)
        embed.add_field(name="Dinero del Club", value=f"💰 ${money:,}", inline=False)
        embed.set_image(url="attachment://pitch.png")
        
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)
        await interaction.followup.send("✅ **Alineación automática aplicada con éxito.**", ephemeral=True)

    @discord.ui.button(label="Seleccionar Capitán", style=discord.ButtonStyle.primary, custom_id="set_captain")
    async def set_captain(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id: return await interaction.response.defer()
        await interaction.response.send_message("👑 Usa el comando `/captain [nombre]` para definir tu capitán.", ephemeral=True)

# ==========================================
# EVENTOS DEL BOT
# ==========================================
@bot.event
async def on_ready():
    global BASE_FIELD_IMAGE, HTTP_SESSION
    print(f"✅ Bot {bot.user.name} conectado y listo.")
    
    # LIGA O SERVIDOR FANTASMA PARA O RENDER NÃO DERRUBAR O BOT
    bot.loop.create_task(start_web_server())

    if HTTP_SESSION is None:
        HTTP_SESSION = aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}) 
        
    if BASE_FIELD_IMAGE is None:
        BASE_FIELD_IMAGE = await asyncio.to_thread(draw_base_field) 
        
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Comandos sincronizados: {len(synced)}")
    except Exception as e:
        print(f"❌ Error sincronizando comandos: {e}")

# ==========================================
# 1. COMANDOS DE JUGADOR Y SISTEMA
# ==========================================
@bot.tree.command(name="help", description="Muestra la lista de todos los comandos disponibles.")
@is_not_locked()
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 Guía de Comandos - SSA Guru",
        description="¡Bienvenido a la guía oficial del bot! Aquí tienes todos los comandos para dominar el juego.",
        color=discord.Color.blue()
    )
    
    jugador_cmds = """
    `/sobre` - Abre una caja misteriosa cada 12h.
    `/claim` - Recluta un jugador aleatorio (10m).
    `/jugadores` - Explora el mercado global.
    `/buy` - Compra un jugador del mercado.
    `/sell` - Vende un jugador de tu inventario.
    `/economia` - Revisa el saldo de tu club.
    `/pay` - Transfiere dinero a otro mánager.
    """
    embed.add_field(name="🎮 Jugador y Economía", value=jugador_cmds, inline=False)
    
    equipo_cmds = """
    `/team` - Mira tu alineación táctica y organiza tu equipo.
    `/nameclub` - Cambia el nombre de tu club.
    `/playersinicial` - Lista tus titulares.
    `/addplayerinicial` - Sube un jugador a titular.
    `/onceinicial` - Manda un titular al banquillo.
    `/matching` - ¡Desafía a un rival a un partido!
    `/ranking` - Mira el Top Global de Victorias.
    """
    embed.add_field(name="⚽ Gestión y Partidos", value=equipo_cmds, inline=False)
    
    admin_cmds = "`/addplayer`, `/editplayer`, `/delplayer`, `/bulkadd`, `/addmoney`, `/removemoney`, `/lock`, `/unlock`, `/claimall`"
    embed.add_field(name="⚙️ Comandos de Admin", value=admin_cmds, inline=False)
    
    embed.set_footer(text="SSA Guru - Street Soccer All One", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="sobre", description="Abre una caja misteriosa a cada 12 horas.")
@is_not_locked()
async def sobre(interaction: discord.Interaction):
    profile = await get_user_profile(interaction.user)
    
    now = datetime.datetime.now().timestamp()
    if now - profile.get("last_sobre", 0) < 43200: 
        restante = 43200 - (now - profile.get("last_sobre", 0))
        horas = int(restante // 3600)
        minutos = int((restante % 3600) // 60)
        return await interaction.response.send_message(f"⏳ Debes esperar **{horas}h {minutos}m** para abrir otro sobre.", ephemeral=True)
    
    caixas = ["Madera", "Hierro", "Oro", "Esmeralda", "Diamante", "SSA Icon"]
    pesos = [40, 30, 15, 8, 5, 2]
    obtenida = random.choices(caixas, weights=pesos, k=1)[0]
    
    recompensa_dinero = caixas.index(obtenida) * 50000 + random.randint(10000, 100000)
    
    profile["money"] += recompensa_dinero
    profile["last_sobre"] = now
    await save_user_profile(interaction.user.id, profile)
    
    embed = discord.Embed(title="🎁 ¡Caja Misteriosa Abierta!", description=f"Has abierto una caja de **{obtenida}**.", color=discord.Color.brand_green())
    embed.add_field(name="Recompensa", value=f"💰 **${recompensa_dinero:,}** añadidos a tu saldo.")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="economia", description="Muestra el saldo y estado financiero de tu club.")
@is_not_locked()
async def economia(interaction: discord.Interaction, usuario: discord.Member = None):
    target = usuario or interaction.user
    profile = await get_user_profile(target)
    
    embed = discord.Embed(title=f"🏦 Economía de {profile['club_name']}", color=discord.Color.gold())
    embed.add_field(name="Saldo Actual", value=f"💰 **${profile['money']:,}**", inline=False)
    embed.add_field(name="Manager", value=target.mention, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="pay", description="Envía dinero a otro jugador.")
@app_commands.describe(usuario="Jugador a pagar", cantidad="Cantidad de dinero")
@is_not_locked()
async def pay(interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
    if cantidad <= 0:
        return await interaction.response.send_message("❌ La cantidad debe ser mayor a 0.", ephemeral=True)
    if usuario.id == interaction.user.id:
        return await interaction.response.send_message("❌ No puedes enviarte dinero a ti mismo.", ephemeral=True)
        
    sender = await get_user_profile(interaction.user)
    if sender["money"] < cantidad:
        return await interaction.response.send_message("❌ No tienes fondos suficientes.", ephemeral=True)
        
    receiver = await get_user_profile(usuario)
    
    sender["money"] -= cantidad
    receiver["money"] += cantidad
    
    await save_user_profile(interaction.user.id, sender)
    await save_user_profile(usuario.id, receiver)
    
    embed = discord.Embed(title="💸 Transferencia Exitosa", description=f"Has enviado **${cantidad:,}** a {usuario.mention}.", color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="buy", description="Busca y contrata a un jugador.")
@is_not_locked()
async def buy(interaction: discord.Interaction, nombre_jugador: str):
    await interaction.response.defer()
    players_data = await get_all_players()
    
    matches = [p["data"] for p in players_data if nombre_jugador.lower() in p["data"]["name"].lower()]
    if not matches:
        return await interaction.followup.send("❌ No se encontró ningún jugador con ese nombre.")
        
    matches.sort(key=lambda x: x["over"], reverse=True)
    
    view = BuyView(interaction.user, matches)
    player = matches[0]
    precio = calculate_price(player["over"])
    
    embed = discord.Embed(title="🛒 Mercado de Fichajes", description=f"Buscando: **{player['name']}**", color=discord.Color.blue())
    embed.add_field(name="Posición", value=player["pos"], inline=True)
    embed.add_field(name="Overall", value=f"⭐ {player['over']}", inline=True)
    embed.add_field(name="Valor de Mercado", value=f"💰 **${precio:,}**", inline=False)
    if player.get("card"):
        embed.set_image(url=player["card"])
        
    view.children[0].disabled = True
    view.children[1].label = f"Comprar (${precio:,})"
    view.children[2].disabled = (len(matches) <= 1)
    
    await interaction.followup.send(embed=embed, view=view)

@bot.tree.command(name="sell", description="Vende a un jugador de tu equipo.")
@is_not_locked()
async def sell(interaction: discord.Interaction, nombre_jugador: str):
    user_profile = await get_user_profile(interaction.user)
    
    matches = [p for p in user_profile["inventory"] if nombre_jugador.lower() in p["name"].lower()]
    if not matches:
        return await interaction.response.send_message("❌ No posees a ese jugador.", ephemeral=True)
        
    target_player = matches[0]
    precio_venta = int(calculate_price(target_player["over"]) * 0.5)
    
    user_profile["inventory"].remove(target_player)
    user_profile["starting_xi"] = [p for p in user_profile["starting_xi"] if p["id"] != target_player["id"]]
    user_profile["money"] += precio_venta
    
    await save_user_profile(interaction.user.id, user_profile)
    
    embed = discord.Embed(title="👋 Venta Completada", description=f"Has vendido a **{target_player['name']}**.", color=discord.Color.red())
    embed.add_field(name="Ingreso", value=f"💰 **${precio_venta:,}**")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="claim", description="Recluta un jugador aleatorio (Cooldown 10 min).")
@is_not_locked()
async def claim(interaction: discord.Interaction):
    profile = await get_user_profile(interaction.user)
    
    now = datetime.datetime.now().timestamp()
    if now - profile.get("last_claim", 0) < 600:
        restante = 600 - (now - profile.get("last_claim", 0))
        minutos = int(restante // 60)
        segundos = int(restante % 60)
        return await interaction.response.send_message(f"⏳ Espera **{minutos}m {segundos}s**.", ephemeral=True)
        
    await interaction.response.defer()
    players_data = await get_all_players()
    if not players_data:
        return await interaction.followup.send("❌ No hay jugadores registrados en el sistema global.")
        
    user_inv_ids = {p["id"] for p in profile.get("inventory", [])}
    available_players = [row["data"] for row in players_data if row["data"]["id"] not in user_inv_ids]
    
    if not available_players:
        return await interaction.followup.send("🎉 **¡Increíble!** Ya tienes absolutamente TODAS las cartas del mercado. ¡Eres una leyenda!")
        
    pesos = []
    for p in available_players:
        over = p.get("over", 50)
        peso = max(1, int(1000 * (0.85 ** (over - 50))))
        pesos.append(peso)
        
    obtenido = random.choices(available_players, weights=pesos, k=1)[0]
    
    profile["last_claim"] = now
    await save_user_profile(interaction.user.id, profile)
    
    precio = calculate_price(obtenido["over"])
    
    embed = discord.Embed(title="🎉 ¡Búsqueda de Talentos!", description=f"Has encontrado a **{obtenido['name']}**.", color=discord.Color.purple())
    embed.add_field(name="Posición", value=obtenido["pos"])
    embed.add_field(name="Overall", value=f"⭐ {obtenido['over']}")
    embed.add_field(name="Valor Estimado", value=f"💰 ${precio:,}")
    if obtenido.get("card"): embed.set_image(url=obtenido["card"])
    
    view = ClaimView(interaction.user, obtenido, precio)
    await interaction.followup.send("¿Qué deseas hacer con este jugador?", embed=embed, view=view)

@bot.tree.command(name="claimall", description="[TESTE] Añade TODOS los jugadores del mercado a tu club.")
@is_not_locked()
async def claimall(interaction: discord.Interaction):
    await interaction.response.defer()
    profile = await get_user_profile(interaction.user)
    
    players_data = await get_all_players()
    if not players_data:
        return await interaction.followup.send("❌ No hay jugadores registrados en el sistema.")
        
    added_count = 0
    existing_ids = {p["id"] for p in profile["inventory"]}
    
    for row in players_data:
        player = row["data"]
        if player["id"] not in existing_ids:
            profile["inventory"].append(player)
            added_count += 1
            
    await save_user_profile(interaction.user.id, profile)
    
    embed = discord.Embed(title="🚀 ¡CLAIM ALL EJECUTADO!", description=f"Se han añadido **{added_count}** nuevos jugadores a tu club para pruebas.", color=discord.Color.brand_green())
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="jugadores", description="Lista todos los jugadores del bot (Mercado Global).")
@is_not_locked()
async def jugadores(interaction: discord.Interaction):
    await interaction.response.defer()
    players_data = await get_all_players()
    
    if not players_data:
        return await interaction.followup.send("No hay jugadores registrados.")
        
    lista = sorted([p["data"] for p in players_data], key=lambda x: x["over"], reverse=True)
    
    pages = []
    chunk_size = 10
    for i in range(0, len(lista), chunk_size):
        chunk = lista[i:i + chunk_size]
        embed = discord.Embed(title="🌐 Mercado Global de Jugadores", color=discord.Color.dark_theme())
        for p in chunk:
            precio = calculate_price(p["over"])
            embed.add_field(name=f"{p['name']} ({p['pos']})", value=f"⭐ Over: {p['over']} | 💰 Costo: ${precio:,}", inline=False)
        embed.set_footer(text=f"Página {i//chunk_size + 1}/{(len(lista)-1)//chunk_size + 1}")
        pages.append(embed)
        
    view = PaginatorView(pages)
    await interaction.followup.send(embed=pages[0], view=view)

@bot.tree.command(name="team", description="Muestra el campo de tu equipo y opciones tácticas.")
@is_not_locked()
async def team(interaction: discord.Interaction):
    await interaction.response.defer()
    profile = await get_user_profile(interaction.user)
    
    if not profile["starting_xi"]:
        embed = discord.Embed(title=f"🏟️ Equipo: {profile['club_name']}", description="Aún no tienes un 11 inicial configurado.", color=discord.Color.red())
        view = TeamView(interaction.user)
        return await interaction.followup.send(embed=embed, view=view)
        
    sigla = profile['club_name'][:3].upper()
    money = profile['money']
    
    overall_total = sum(p["over"] for p in profile["starting_xi"]) if profile["starting_xi"] else 0
    
    image_buffer = await optimized_generate_pitch_image(profile["starting_xi"], profile["club_name"], sigla, money, overall_total)
    file = discord.File(image_buffer, filename="pitch.png")
    
    embed = discord.Embed(title=f"🏟️ Prancheta Tática: {profile['club_name']}", color=discord.Color.dark_green())
    embed.add_field(name="Rating del Equipo (SOMA)", value=f"⭐ {overall_total}", inline=True)
    embed.add_field(name="Formación", value="4-3-3 (Dinámico)", inline=True)
    embed.add_field(name="Dinero del Club", value=f"💰 ${money:,}", inline=False)
    embed.set_image(url="attachment://pitch.png")
    
    view = TeamView(interaction.user)
    await interaction.followup.send(embed=embed, file=file, view=view)

# ==========================================
# 2. COMANDOS DE GESTIÓN DE EQUIPO
# ==========================================
@bot.tree.command(name="nameclub", description="Cambia el nombre de tu club.")
@is_not_locked()
async def nameclub(interaction: discord.Interaction, nombre: str):
    profile = await get_user_profile(interaction.user)
    profile["club_name"] = nombre[:30]
    await save_user_profile(interaction.user.id, profile)
    await interaction.response.send_message(f"✅ El nombre de tu club ahora es **{nombre[:30]}**.", ephemeral=True)

@bot.tree.command(name="playersinicial", description="Lista los jugadores en tu 11 titular.")
@is_not_locked()
async def playersinicial(interaction: discord.Interaction):
    profile = await get_user_profile(interaction.user)
    xi = profile["starting_xi"]
    if not xi: return await interaction.response.send_message("Tu 11 inicial está vacío.", ephemeral=True)
    desc = "\n".join([f"**{p['name']}** - {p['pos']} (⭐ {p['over']})" for p in xi])
    embed = discord.Embed(title=f"⚽ 11 Titular de {profile['club_name']}", description=desc, color=discord.Color.orange())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="addplayerinicial", description="Añade un jugador a tu 11 titular.")
@is_not_locked()
async def addplayerinicial(interaction: discord.Interaction, nombre: str):
    profile = await get_user_profile(interaction.user)
    if len(profile["starting_xi"]) >= 11:
        return await interaction.response.send_message("❌ Tu 11 inicial ya está lleno (11 jugadores).", ephemeral=True)
    matches = [p for p in profile["inventory"] if nombre.lower() in p["name"].lower()]
    if not matches:
        return await interaction.response.send_message("❌ No tienes ese jugador.", ephemeral=True)
    target = matches[0]
    if any(p["id"] == target["id"] for p in profile["starting_xi"]):
        return await interaction.response.send_message("❌ Ya está en el 11 titular.", ephemeral=True)
    profile["starting_xi"].append(target)
    await save_user_profile(interaction.user.id, profile)
    await interaction.response.send_message(f"✅ **{target['name']}** ha sido añadido al 11 titular.", ephemeral=True)

@bot.tree.command(name="onceinicial", description="Envía a un jugador titular al banquillo.")
@is_not_locked()
async def onceinicial(interaction: discord.Interaction, nombre: str):
    profile = await get_user_profile(interaction.user)
    matches = [p for p in profile["starting_xi"] if nombre.lower() in p["name"].lower()]
    if not matches:
        return await interaction.response.send_message("❌ Ese jugador no está en tu 11 titular.", ephemeral=True)
    target = matches[0]
    profile["starting_xi"] = [p for p in profile["starting_xi"] if p["id"] != target["id"]]
    await save_user_profile(interaction.user.id, profile)
    await interaction.response.send_message(f"⬇️ **{target['name']}** ha sido enviado al banquillo.", ephemeral=True)

# --- CLASSE E COMANDO DO DUELO (MATCHING) ---
class MatchAcceptView(discord.ui.View):
    def __init__(self, author, oponente):
        super().__init__(timeout=60)
        self.author = author
        self.oponente = oponente
        self.accepted = None

    @discord.ui.button(label="Aceptar Desafío", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.oponente.id:
            return await interaction.response.send_message("❌ ¡Solo el desafiado puede aceptar el duelo!", ephemeral=True)
        self.accepted = True
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.oponente.id:
            return await interaction.response.send_message("❌ ¡Solo el desafiado puede rechazar el duelo!", ephemeral=True)
        self.accepted = False
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"🚫 **¡Cobarde!** El miedo dominó el vestuario de **{self.oponente.display_name}** y huyó del partido.")
        self.stop()

@bot.tree.command(name="matching", description="Desafía a un oponente a un duelo 11v11 en la SSA Arena.")
@is_not_locked()
async def matching(interaction: discord.Interaction, rival: discord.Member):
    if rival.id == interaction.user.id:
        return await interaction.response.send_message("❌ No puedes jugar contra ti mismo.", ephemeral=True)
        
    p1_profile = await get_user_profile(interaction.user)
    p2_profile = await get_user_profile(rival)
    
    p1_xi = p1_profile["starting_xi"]
    p2_xi = p2_profile["starting_xi"]
    
    if len(p1_xi) < 11:
        return await interaction.response.send_message("❌ Tu equipo NO está completo. Necesitas 11 titulares.", ephemeral=True)
    if len(p2_xi) < 11:
        return await interaction.response.send_message(f"❌ El equipo de {rival.display_name} NO está completo.", ephemeral=True)
        
    p1_fuerza = sum(p["over"] for p in p1_xi)
    p2_fuerza = sum(p["over"] for p in p2_xi)
    
    embed_convite = discord.Embed(
        title="⚔️ ¡NUEVO DESAFÍO EN EL CAMPO!",
        description=f"**{interaction.user.display_name}** ha lanzado el guante y desafía a {rival.mention} a un partido oficial.",
        color=discord.Color.red()
    )
    embed_convite.add_field(name="🏟️ Estadio", value="SSA Arena", inline=True)
    embed_convite.add_field(name="🏆 En Juego", value="El Honor y los Puntos", inline=True)
    embed_convite.set_footer(text="¡El desafiado tiene 60 segundos para aceptar o quedar como un cobarde!")

    view = MatchAcceptView(interaction.user, rival)
    await interaction.response.send_message(content=rival.mention, embed=embed_convite, view=view)
    
    await view.wait()
    
    if view.accepted is None:
        return await interaction.followup.send(f"⏱️ El tiempo expiró. **{rival.display_name}** no se atrevió a salir al campo.")
    elif not view.accepted:
        return 
        
    message = await interaction.original_response()
    embed_jogo = discord.Embed(title="🎙️ TRANSMISIÓN EN VIVO - SSA TV", description="```\nEl balón está a punto de rodar...\n```", color=discord.Color.green())
    await message.edit(content=f"🏟️ **¡La afición en la SSA Arena enloquece! ¡El árbitro pita el inicio!**", embed=embed_jogo, view=None)
    
    p1_goles = 0
    p2_goles = 0
    historial_eventos = []
    minuto_actual = 0
    
    narrativas = {
        "gol": [
            "⚽ ¡GOOOOOOOLAZO! {atk} fusiló al portero {gk} tras una asistencia de {ast}.",
            "⚽ ¡GOL GOL GOL GOL! {atk} dejó a {defensor} en el suelo y la mandó a guardar.",
            "⚽ ¡QUÉ DEFINICIÓN! {atk} pica el balón sobre {gk} con una clase magistral.",
            "⚽ ¡GOL DE CABEZA! Centro medido de {ast} y {atk} se eleva por los cielos.",
            "⚽ ¡ZAPATAZO IMPARABLE! {atk} rompe las redes desde fuera del área."
        ],
        "defesa": [
            "🧤 ¡SAN {gk}! Vuelo espectacular para sacar el disparo de {atk} del ángulo.",
            "🛡️ ¡LA MURALLA! {defensor} se cruza en el último segundo para bloquear a {atk}.",
            "🧤 ¡QUÉ REFLEJOS! {atk} remata a quemarropa pero {gk} salva milagrosamente.",
            "🛡️ ¡CORTE PROVIDENCIAL! {defensor} lee la jugada y le roba el gol a {atk}."
        ],
        "erro": [
            "❌ ¡A LAS NUBES! {atk} la manda al tercer anfiteatro. Saque de puerta.",
            "❌ ¡AL PALO! El disparo de {atk} hace temblar el travesaño. ¡Se salva el equipo!",
            "❌ ¡NO ME LO CREO! {atk} falla a puerta vacía tras el pase de {ast}.",
            "⚠️ ¡FALTA TÁCTICA! {defensor} derriba a {atk} para frenar el contragolpe."
        ]
    }
    
    while minuto_actual < 90:
        await asyncio.sleep(2.5) 
        minuto_actual += random.randint(5, 11) 
        if minuto_actual > 90: minuto_actual = 90
        
        prob_p1 = p1_fuerza / (p1_fuerza + p2_fuerza)
        is_p1_attack = random.random() < prob_p1
        
        atk_team, atk_xi = (p1_profile, p1_xi) if is_p1_attack else (p2_profile, p2_xi)
        def_team, def_xi = (p2_profile, p2_xi) if is_p1_attack else (p1_profile, p1_xi)
        
        atacante = get_random_player_name(atk_xi, ["DC", "MID"])
        asistente = get_random_player_name(atk_xi, ["MID", "DFC"])
        defensor = get_random_player_name(def_xi, ["DFC", "MID"])
        portero = get_random_player_name(def_xi, ["PO"])
        
        dice = random.random()
        if dice < 0.35: # Gol
            if is_p1_attack: p1_goles += 1
            else: p2_goles += 1
            lance = random.choice(narrativas["gol"]).format(atk=atacante, ast=asistente, gk=portero, defensor=defensor)
        elif dice < 0.70: # Defesa
            lance = random.choice(narrativas["defesa"]).format(atk=atacante, gk=portero, defensor=defensor)
        else: # Erro
            lance = random.choice(narrativas["erro"]).format(atk=atacante, gk=portero, ast=asistente, defensor=defensor)
            
        historial_eventos.append(f"[{minuto_actual:02d}'] {lance}")
        texto_log = "\n\n".join(historial_eventos[-8:]) 
        
        embed_jogo.description = f"```\n{texto_log}\n```"
        embed_jogo.clear_fields()
        
        embed_jogo.add_field(name=f"🏠 {p1_profile['club_name']}", value=f"> **{p1_goles}**", inline=True)
        embed_jogo.add_field(name="⚔️", value="VS", inline=True)
        embed_jogo.add_field(name=f"✈️ {p2_profile['club_name']}", value=f"> **{p2_goles}**", inline=True)
        
        await message.edit(embed=embed_jogo)
        
    await asyncio.sleep(2)
    final_embed = discord.Embed(title="🏁 ¡FINAL DEL PARTIDO EN LA SSA ARENA!", color=discord.Color.dark_gold())
    final_embed.description = f"```\n{chr(10).join(historial_eventos)}\n```" 
    resultado = f"**{p1_profile['club_name']}** `{p1_goles}` - `{p2_goles}` **{p2_profile['club_name']}**"
    final_embed.add_field(name="MARCADOR FINAL", value=resultado, inline=False)
    
    if p1_goles > p2_goles:
        p1_profile["wins"] += 1
        p2_profile["losses"] += 1
        final_embed.set_footer(text=f"🏆 ¡Victoria espectacular para {p1_profile['club_name']}!")
    elif p2_goles > p1_goles:
        p2_profile["wins"] += 1
        p1_profile["losses"] += 1
        final_embed.set_footer(text=f"🏆 ¡Victoria espectacular para {p2_profile['club_name']}!")
    else:
        final_embed.set_footer(text="🤝 ¡Todo igual! Fin del partido.")
        
    await save_user_profile(interaction.user.id, p1_profile)
    await save_user_profile(rival.id, p2_profile)
    await message.edit(content="🎙️ **Transmisión finalizada.**", embed=final_embed)

@bot.tree.command(name="ranking", description="Muestra el ranking global de victorias.")
@is_not_locked()
async def ranking(interaction: discord.Interaction):
    users_data = await get_all_users()
    if not users_data: return await interaction.response.send_message("No hay datos.", ephemeral=True)
    usuarios_validos = [u["data"] for u in users_data if "wins" in u["data"]]
    ranking_list = sorted(usuarios_validos, key=lambda x: x.get("wins", 0), reverse=True)[:10]
    
    embed = discord.Embed(title="🏆 SSA Guru - Ranking Mundial", color=discord.Color.gold())
    desc = ""
    for idx, user in enumerate(ranking_list, 1):
        icono = ["🥇", "🥈", "🥉"][idx-1] if idx <= 3 else "🏅"
        desc += f"{icono} **#{idx}** | **{user.get('club_name', 'Desconocido')}** - Victorias: `{user.get('wins', 0)}`\n"
    embed.description = desc
    await interaction.response.send_message(embed=embed)

# ==========================================
# 3. COMANDOS ADMINISTRATIVOS
# ==========================================
@bot.tree.command(name="bulkadd", description="Admin: Añade múltiples jugadores subiendo un archivo .txt.")
@app_commands.describe(archivo="Archivo .txt con formato: Nick OVR POS LINK (uno por línea)")
@app_commands.checks.has_permissions(administrator=True)
async def bulkadd(interaction: discord.Interaction, archivo: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    
    if not archivo.filename.endswith('.txt'):
        return await interaction.followup.send("❌ Por favor, sube un archivo con extensión .txt.")
        
    try:
        file_bytes = await archivo.read()
        content = file_bytes.decode('utf-8')
    except Exception as e:
        return await interaction.followup.send("❌ Error al leer el archivo. Asegúrate de que sea un archivo de texto válido.")
        
    lineas = content.splitlines()
    count = 0
    errores = []
    
    for i, linea in enumerate(lineas, 1):
        linea = linea.strip()
        if not linea: continue
        
        partes = linea.split()
        if len(partes) < 4:
            errores.append(f"Línea {i}: Formato incompleto. Usa: Nick OVR POS LINK.")
            continue
            
        card_url = partes[-1]
        pos = partes[-2].upper()
        
        try:
            over = int(partes[-3])
        except ValueError:
            errores.append(f"Línea {i}: El Over debe ser un número. Encontrado: '{partes[-3]}'")
            continue
            
        nick = " ".join(partes[:-3])
        
        player_id = f"player_{str(uuid.uuid4())[:8]}"
        await db_upsert(player_id, {"id": player_id, "name": nick, "over": over, "pos": pos, "card": card_url})
        count += 1
        
    msg = f"✅ **¡GG!** {count} jugadores añadidos exitosamente al sistema desde el archivo."
    if errores:
        msg += f"\n⚠️ Hubo {len(errores)} errores (líneas ignoradas). Ej: {errores[0]}"
        
    await interaction.followup.send(msg)

@bot.tree.command(name="addplayer", description="Admin: Añade un jugador (URL o Archivo adjunto).")
@app_commands.checks.has_permissions(administrator=True)
async def addplayer(interaction: discord.Interaction, nick: str, over: int, posicion: str, url_imagen: str = None, imagem_anexada: discord.Attachment = None):
    posiciones = ["PO", "DFC", "MCD", "MC", "MCO", "DC"]
    if posicion.upper() not in posiciones:
        return await interaction.response.send_message(f"❌ Posición inválida. Usa: {', '.join(posiciones)}", ephemeral=True)
        
    final_url = imagem_anexada.url if imagem_anexada else url_imagen
    if final_url:
        final_url = final_url.strip()
        if not final_url.startswith("http"):
            final_url = "https://" + final_url
            
    player_id = f"player_{str(uuid.uuid4())[:8]}"
    await db_upsert(player_id, {"id": player_id, "name": nick, "over": over, "pos": posicion.upper(), "card": final_url})
    
    embed = discord.Embed(title="✅ Jugador Añadido", description=f"**{nick}** ha sido añadido exitosamente.", color=discord.Color.green())
    if final_url:
        embed.set_thumbnail(url=final_url)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="editplayer", description="Admin: Edita un jugador existente (Sincroniza globalmente).")
@app_commands.checks.has_permissions(administrator=True)
async def editplayer(interaction: discord.Interaction, nombre: str, nuevo_over: int = None, nueva_pos: str = None, url_imagen: str = None, imagem_anexada: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True)
    players = await get_all_players()
    matches = [p for p in players if nombre.lower() in p["data"]["name"].lower()]
    if not matches: return await interaction.followup.send("❌ Jugador no encontrado.")
    
    data = matches[0]["data"]
    old_pos = data["pos"]
    if nuevo_over: data["over"] = nuevo_over
    if nueva_pos: data["pos"] = nueva_pos.upper()
    
    final_url = imagem_anexada.url if imagem_anexada else url_imagen
    if final_url:
        final_url = final_url.strip()
        if not final_url.startswith("http"):
            final_url = "https://" + final_url
        data["card"] = final_url
        
    await db_upsert(data["id"], data)
    
    users = await get_all_users()
    updated_users = 0
    for u in users:
        profile = u["data"]
        changed = False
        
        if data["id"] in PLAYER_CARD_CACHE:
            del PLAYER_CARD_CACHE[data["id"]]
            
        for i, p in enumerate(profile.get("inventory", [])):
            if p["id"] == data["id"]:
                profile["inventory"][i] = data
                changed = True
                
        new_xi = []
        for p in profile.get("starting_xi", []):
            if p["id"] == data["id"]:
                if get_pos_group(old_pos) == get_pos_group(data["pos"]):
                    new_xi.append(data) 
                changed = True
            else:
                new_xi.append(p)
        profile["starting_xi"] = new_xi
        
        if changed:
            try:
                u_id_int = int(u["id"].split("_")[1])
                await save_user_profile(u_id_int, profile)
                updated_users += 1
            except: pass

    embed = discord.Embed(title="✅ Jugador Actualizado", description=f"**{data['name']}** ha sido modificado.\nSincronizado en {updated_users} clube(s). Cache de imagen limpio.", color=discord.Color.green())
    if data.get("card"):
        embed.set_thumbnail(url=data["card"])
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="delplayer", description="Admin: Elimina un jugador.")
@app_commands.checks.has_permissions(administrator=True)
async def delplayer(interaction: discord.Interaction, nombre: str):
    await interaction.response.defer(ephemeral=True)
    players = await get_all_players()
    matches = [p for p in players if nombre.lower() in p["data"]["name"].lower()]
    if not matches: return await interaction.followup.send("❌ Jugador no encontrado.")
    player_id_del = matches[0]["data"]["id"]
    await db_delete(player_id_del)
    
    if player_id_del in PLAYER_CARD_CACHE:
        del PLAYER_CARD_CACHE[player_id_del]
        
    await interaction.followup.send(f"🗑️ Jugador eliminado y cache limpio.")

@bot.tree.command(name="lock", description="Admin: Bloquea comandos.")
@app_commands.checks.has_permissions(administrator=True)
async def lock(interaction: discord.Interaction):
    global bot_locked
    bot_locked = True
    await interaction.response.send_message("🔒 **Mantenimiento ACTIVADO. Comandos bloqueados.**")

@bot.tree.command(name="unlock", description="Admin: Desbloquea comandos.")
@app_commands.checks.has_permissions(administrator=True)
async def unlock(interaction: discord.Interaction):
    global bot_locked
    bot_locked = False
    await interaction.response.send_message("🔓 **Mantenimiento DESACTIVADO. Comandos desbloqueados.**")

@bot.tree.command(name="addmoney", description="Admin: Añade dinero.")
@app_commands.checks.has_permissions(administrator=True)
async def addmoney(interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
    profile = await get_user_profile(usuario)
    profile["money"] += cantidad
    await save_user_profile(usuario.id, profile)
    await interaction.response.send_message(f"💰 Añadidos **${cantidad:,}** a {usuario.mention}.", ephemeral=True)

@bot.tree.command(name="removemoney", description="Admin: Quita dinero.")
@app_commands.checks.has_permissions(administrator=True)
async def removemoney(interaction: discord.Interaction, usuario: discord.Member, cantidad: int):
    profile = await get_user_profile(usuario)
    profile["money"] = max(0, profile["money"] - cantidad)
    await save_user_profile(usuario.id, profile)
    await interaction.response.send_message(f"📉 Retirados **${cantidad:,}** de {usuario.mention}.", ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ No tienes permisos de administrador para usar esto.", ephemeral=True)

# ==========================================
# EJECUCIÓN DEL BOT
# ==========================================
if __name__ == "__main__":
    if not os.path.exists("renogare.otf"):
        print("⚠️ ARCHIVO 'renogare.otf' NO ENCONTRADO.")
        print("Asegúrate de colocar 'renogare.otf' en la mesma pasta que este script.")
        print("El bot usará la fuente por defecto para las imágenes generadas.")
        
    bot.run(DISCORD_TOKEN)