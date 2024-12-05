from fastapi import FastAPI, BackgroundTasks, Query, Request, HTTPException, Depends
import asyncio
import aiohttp
import aiofiles
from PIL import Image, ImageFont, ImageDraw
from datetime import datetime
import os
import time
import shutil
from functools import partial
from concurrent.futures import ProcessPoolExecutor
import json
import glob
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from merger import merger

# Global variables and configurations
itemShopFont = 'assets/BurbankBigRegular-BlackItalic.otf'  # the font you wish to use
overlayPath = "assets/overlay.png"
hash_file = 'hash.json'
hash_data = {"hash": ""}

checkForOgItems = True  # If false, it will not generate the og items image.
ogThreshold = 100  # Threshold to consider an item 'og' (isn't used if checkForOgItems is false)

normalTitleText = "Item Shop"  # Title for the main item shop image
ogTitleText = "OG Items"  # Title for the OG items image

showDateNormal = True  # Should the date be shown in the normal image?
showDateOg = True  # Should the date be shown in the OG items image?

def load_hash():
    global hash_data
    if os.path.exists(hash_file):
        with open(hash_file, 'r') as f:
            hash_data = json.load(f)
    else:
        hash_data = {"hash": ""}

def save_hash():
    with open(hash_file, 'w') as f:
        json.dump(hash_data, f)

async def check_and_update_shop():
    while True:
        await check_shop_update()
        await asyncio.sleep(900)  # Wait for 15 minutes

async def check_shop_update():
    load_hash()
    current_hash = hash_data.get('hash', '')
    print(f"Current saved hash: {current_hash}")

    async with aiohttp.ClientSession() as session:
        async with session.get('https://fortnite-api.com/v2/shop') as resp:
            if resp.status != 200:
                print("Failed to fetch shop data.")
                return
            data = await resp.json()
            shop_data = data['data']
            new_hash = shop_data['hash']

            if new_hash != current_hash:
                print("Hash has changed, regenerating shop images.")
                hash_data['hash'] = new_hash
                save_hash()

                await genshop(session, shop_data, new_hash)
                if checkForOgItems:
                    await ogitems(session, shop_data, new_hash)
                else:
                    print("Og items is disabled.")

                move_old_images_to_archive(new_hash)
            else:
                print("Hash has not changed.")

def move_old_images_to_archive(new_hash):
    os.makedirs('shops/archive', exist_ok=True)
    os.makedirs('shops/archive/og', exist_ok=True)

    for filename in glob.glob('shops/shop-*.jpg'):
        if new_hash not in filename:
            shutil.move(filename, os.path.join('shops/archive', os.path.basename(filename)))

    for filename in glob.glob('shops/og/og-*.jpg'):
        if new_hash not in filename:
            shutil.move(filename, os.path.join('shops/archive/og', os.path.basename(filename)))

async def genshop(session, shop_data, shop_hash, custom=False, custom_params=None, saveAs=None, key=None):
    print("Generating the Fortnite Item Shop.")

    shutil.rmtree('cache', ignore_errors=True)
    os.makedirs('cache', exist_ok=True)

    start = time.time()

    currentdate = shop_data['date'][:10]
    entries = shop_data['entries']
    item_data_list = []

    if entries:
        for entry in entries:
            i = entry

            url = None

            tracks = i.get('tracks', None)

            offertag = i.get('offerTag', {})
            offerId = offertag.get('id', "")

            brItemsfrfr = i.get('brItems', None)

            if offerId == "sparksjamloop":
                continue

            if tracks:
                continue

            if not brItemsfrfr:
                continue


            new_display_asset = i.get('newDisplayAsset', {})
            material_instances = new_display_asset.get('materialInstances', [])
            if material_instances:
                images = material_instances[0].get('images', {})
                url = images.get('Background') or images.get('OfferImage')
            else:
                render_images = new_display_asset.get('renderImages', [])
                if render_images:
                    url = render_images[0].get('image')

            if not url:
                url = i['brItems'][0]['images']['icon']

            last_seen = i['brItems'][0].get('shopHistory', [])
            last_seen_date = last_seen[-2][:10] if len(last_seen) >= 2 else 'NEW!'
            price = i['finalPrice']

            if i.get('bundle'):
                url = i['bundle']['image']
                filename = f"zzz{i['bundle']['name']}"
                name = i['bundle']['name']
            else:
                filename = i['brItems'][0]['id']
                name = i['brItems'][0]['name']

            if last_seen_date != 'NEW!':
                diff_days = (datetime.strptime(currentdate, "%Y-%m-%d") - datetime.strptime(last_seen_date, "%Y-%m-%d")).days
                diff = str(diff_days or 1)
            else:
                diff = 'NEW!'

            item_data = {
                'filename': filename,
                'url': url,
                'i': i,
                'diff': diff,
                'price': price,
                'name': name,
                'currentdate': currentdate,
            }
            item_data_list.append(item_data)

        download_tasks = [download_image(session, item['url'], item['filename']) for item in item_data_list]
        await asyncio.gather(*download_tasks)

        overlay = Image.open(overlayPath).convert('RGBA')
        process_partial = partial(process_item, overlay=overlay, font_path=itemShopFont)

        with ProcessPoolExecutor() as executor:
            loop = asyncio.get_running_loop()
            tasks = [loop.run_in_executor(executor, process_partial, item_data) for item_data in item_data_list]
            await asyncio.gather(*tasks)

        print(f'Done generating "{len(item_data_list)}" items in the Featured section.')

        print(f'\nGenerated {len(item_data_list)} items from the {currentdate} Item Shop.')

        print('\nMerging images...')
        if custom and custom_params:
            await asyncio.to_thread(
                merger,
                ogitems=False,
                currentdate=currentdate,
                shop_hash=shop_hash,
                custom=custom,
                title_text=custom_params['normTitle'],
                showDate=custom_params['normalShowDate'],
                saveAsName=saveAs,
                key=key
            )
        else:
            await asyncio.to_thread(
                merger,
                ogitems=False,
                currentdate=currentdate,
                shop_hash=shop_hash,
                custom=custom,
                title_text=normalTitleText,
                showDate=showDateNormal
            )

        end = time.time()

        print(f"IMAGE GENERATING COMPLETE - Generated image in {round(end - start, 2)} seconds!")

async def ogitems(session, shop_data, shop_hash, custom=False, custom_params=None, saveAs=None, key=None):
    shutil.rmtree('ogcache', ignore_errors=True)
    os.makedirs('ogcache', exist_ok=True)

    start = time.time()

    currentdate = shop_data['date'][:10]
    entries = shop_data['entries']

    threshold = ogThreshold

    if custom and custom_params:
        threshold = custom_params.get('ogThreshold', ogThreshold)

    if not entries:
        print(f'No items found in the {currentdate} Item Shop.')
        return

    resultlist = []
    for entry in entries:

        i = entry

        tracks = i.get('tracks', None)

        offertag = i.get('offerTag', {})
        offerId = offertag.get('id', "")

        brItemsfrfr = i.get('brItems', None)

        if offerId == "sparksjamloop":
            continue

        if tracks:
            continue

        if not brItemsfrfr:
            continue


        brItems = i['brItems'][0]

        shophistory = i['brItems'][0].get('shopHistory', [])
        lastseen_date = shophistory[-2][:10] if len(shophistory) >= 2 else currentdate
        days_since_last_seen = (datetime.strptime(currentdate, "%Y-%m-%d") - datetime.strptime(lastseen_date, "%Y-%m-%d")).days
        if days_since_last_seen >= threshold:
            price = i['finalPrice']
            resultlist.append({
                "name": brItems['name'],
                "id": brItems['id'],
                "lastseen_days": str(days_since_last_seen),
                "lastseen_date": lastseen_date,
                "type": brItems['type']['displayValue'],
                "price": price,
                "item_data": brItems
            })

    if not resultlist:
        print('There are no rare items.')
        return

    print('Rare cosmetics have been found')
    rarest_item = max(resultlist, key=lambda x: int(x['lastseen_days']))
    print(f"The rarest item is the {rarest_item['name']} {rarest_item['type']}, which hasn't been seen in {rarest_item['lastseen_days']} days!")

    print("Rare items:")
    for item in resultlist:
        print(f"- {item['name']} ({item['lastseen_days']} days)\n")

    download_tasks = []
    for item in resultlist:
        filename = f"OG{item['id']}"
        fpath = f'ogcache/{filename}.png'
        if not os.path.exists(fpath):
            itm = item['item_data']
            url = None

            new_display_asset = itm.get('newDisplayAsset', {})
            material_instances = new_display_asset.get('materialInstances', [])
            if material_instances:
                images = material_instances[0].get('images', {})
                url = images.get('Background') or images.get('OfferImage')
            else:
                render_images = new_display_asset.get('renderImages', [])
                if render_images:
                    url = render_images[0].get('image')

            if not url:
                url = itm['images']['icon']

            if url:
                download_tasks.append(download_image(session, url, filename, folder='ogcache'))

    await asyncio.gather(*download_tasks)

    overlay = Image.open(overlayPath).convert('RGBA')
    process_partial = partial(process_og_item, overlay=overlay, font_path=itemShopFont)

    with ProcessPoolExecutor() as executor:
        loop = asyncio.get_running_loop()
        tasks = [loop.run_in_executor(executor, process_partial, item) for item in resultlist]
        await asyncio.gather(*tasks)

    if custom and custom_params:
        await asyncio.to_thread(
            merger,
            ogitems=True,
            currentdate=currentdate,
            shop_hash=shop_hash,
            custom=custom,
            title_text=custom_params['ogTitle'],
            showDate=custom_params['ogShowDate'],
            saveAsName=saveAs,
            key=key
        )
    else:
        await asyncio.to_thread(
            merger,
            ogitems=True,
            currentdate=currentdate,
            shop_hash=shop_hash,
            custom=custom,
            title_text=ogTitleText,
            showDate=showDateOg
        )
    print(f"Saved in shops/og folder as 'og-{shop_hash}.jpg'.\n")

    end = time.time()
    print(f"OG ITEMS IMAGE GENERATING COMPLETE - Generated image in {round(end - start, 2)} seconds!")

async def download_image(session, url, filename, folder='cache'):
    try:
        os.makedirs(folder, exist_ok=True)
        fpath = f'{folder}/{filename}.png'
        async with session.get(url) as response:
            if response.status == 200:
                async with aiofiles.open(fpath, 'wb') as f:
                    await f.write(await response.read())
                return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
    return False

def process_item(item_data, overlay, font_path):
    filename = item_data['filename']
    diff = item_data['diff']
    price = item_data['price']
    name = item_data['name']

    try:
        with Image.open(f'cache/{filename}.png') as background:
            background = background.resize((512, 512))
            img = Image.new("RGBA", (512, 512))
            img.paste(background)

            img.paste(overlay, (0, 0), overlay)

            draw = ImageDraw.Draw(img)

            font = ImageFont.truetype(font_path, 35)
            draw.text((256, 420), name, font=font, fill='white', anchor='ms')

            diff_text = 'NEW!' if 'NEW!' in diff else f'LAST SEEN: {diff} day{"s" if diff != "1" else ""} ago'
            font = ImageFont.truetype(font_path, 15)
            draw.text((256, 450), diff_text, font=font, fill='white', anchor='ms')

            font = ImageFont.truetype(font_path, 40)
            draw.text((256, 505), f'{price}', font=font, fill='white', anchor='ms')

            img.save(f'cache/{filename}.png')
    except Exception as e:
        print(f"Error processing item {filename}: {e}")

def process_og_item(item, overlay, font_path):
    filename = f"OG{item['id']}"
    try:
        with Image.open(f'ogcache/{filename}.png') as background:
            background = background.resize((512, 512))
            img = Image.new("RGBA", (512, 512))
            img.paste(background)

            img.paste(overlay, (0, 0), overlay)

            draw = ImageDraw.Draw(img)

            font = ImageFont.truetype(font_path, 35)
            draw.text((256, 420), item['name'], font=font, fill='white', anchor='ms')

            last_seen_days = item['lastseen_days']
            diff_text = f'LAST SEEN: {last_seen_days} day{"s" if last_seen_days != "1" else ""} ago'
            font = ImageFont.truetype(font_path, 15)
            draw.text((256, 450), diff_text, font=font, fill='white', anchor='ms')

            price = item['price']
            font = ImageFont.truetype(font_path, 40)
            draw.text((256, 505), f'{price}', font=font, fill='white', anchor='ms')

            img.save(f'ogcache/{filename}.png')
    except Exception as e:
        print(f"Error processing OG item {filename}: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    task = asyncio.create_task(check_and_update_shop())
    yield
    # Shutdown code
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

app.mount("/shops", StaticFiles(directory="shops"), name="shops")

app.mount("/shops/og", StaticFiles(directory="shops/og"), name="shops/og")

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root(request: Request):
    load_hash()
    current_hash = hash_data.get('hash', '')
    return templates.TemplateResponse("index.html", {"request": request, "hash": current_hash})

@app.get("/api/v1/info")
async def get_info():
    load_hash()
    current_hash = hash_data.get('hash', '')

    normal_shop_link = f"/shops/shop-{current_hash}.jpg"
    og_shop_link = f"/shops/og/og-{current_hash}.jpg"

    return {
        "hash": current_hash,
        "normalShopLink": normal_shop_link,
        "ogShopLink": og_shop_link
    }

@app.get("/api/v1/archive")
async def get_archive():
    archive_data = {}
    # Get all shop images in shops/ and shops/archive/
    shop_files = glob.glob('shops/archive/shop-*.jpg')
    og_files = glob.glob('shops/archive/og/og-*.jpg')

    for filepath in shop_files:
        filename = os.path.basename(filepath)
        hash_part = filename.split('-')[1].split('.')[0]
        archive_data.setdefault(hash_part, {})
        archive_data[hash_part]['normalShopLink'] = f"/shops/archive/{filename}"

    for filepath in og_files:
        filename = os.path.basename(filepath)
        hash_part = filename.split('-')[1].split('.')[0]
        archive_data.setdefault(hash_part, {})
        archive_data[hash_part]['ogLink'] = f"/shops/archive/og/{filename}"

    return archive_data

# Dependency to check adminKey
def check_admin_key(adminKey: str = Query(...)):
    if adminKey != "90313-999":
        raise HTTPException(status_code=401, detail="Invalid admin key")



@app.get('/api/v1/fngg/getVideo', include_in_schema=True)
async def fnggVideo(
    cosmeticid: str = Query(...)
):
    fnggdata = {}
    async with aiohttp.ClientSession() as session:
        async with session.get('https://fortnite.gg/api/items.json') as resp:
            if resp.status != 200:
                print("Failed to fetch fngg data.")
                return {"status": "Failed to fetch fngg data."}
            data = await resp.json()

            for key, value in data.items():
                fnggdata[key.lower()] = value

            cosmeticfnggid = fnggdata.get(cosmeticid.lower())
            if cosmeticfnggid is None:
                return {"status": "Failed to fetch fngg data for that cosmetic."}

            return {
                'status': 'success',
                'fnggid': cosmeticfnggid,
                'videourl': f'https://fnggcdn.com/items/{cosmeticfnggid}/video.mp4'
            }



@app.get("/api/v1/shop/forceRegen", include_in_schema=False)
async def force_regen(adminKey: str = Depends(check_admin_key)):
    print("Force regenerating shop images.")
    async with aiohttp.ClientSession() as session:
        async with session.get('https://fortnite-api.com/v2/shop?responseFlags=0x7') as resp:
            if resp.status != 200:
                print("Failed to fetch shop data.")
                return {"status": "Failed to fetch shop data."}
            data = await resp.json()
            shop_data = data['data']
            new_hash = shop_data['hash']
            currentdate = shop_data['date'][:10]

            hash_data['hash'] = new_hash
            save_hash()

            # Generate shop images
            await genshop(session, shop_data, new_hash)
            if checkForOgItems:
                await ogitems(session, shop_data, new_hash)
            else:
                print("Og items is disabled.")

            # Move old images to archive
            move_old_images_to_archive(new_hash)

            return {"status": "Shop images regenerated.", "hash": new_hash}

@app.get("/api/v1/shop/createCustom", include_in_schema=True)
async def create_custom(
    adminKey: str = Depends(check_admin_key),
    normTitle: str = Query(default=normalTitleText),
    ogTitle: str = Query(default=ogTitleText),
    normalShowDate: bool = Query(default=showDateNormal),
    ogShowDate: bool = Query(default=showDateOg),
    ogThresholdParam: int = Query(default=ogThreshold),
    saveAs: str = Query(...),
    key: str = Query(...)
):
    print("Creating custom shop images.")

    # Custom parameters
    custom_params = {
        'normTitle': normTitle,
        'ogTitle': ogTitle,
        'normalShowDate': normalShowDate,
        'ogShowDate': ogShowDate,
        'ogThreshold': ogThresholdParam
    }

    async with aiohttp.ClientSession() as session:
        async with session.get('https://fortnite-api.com/v2/shop?responseFlags=0x7') as resp:
            if resp.status != 200:
                print("Failed to fetch shop data.")
                return {"status": "Failed to fetch shop data."}
            data = await resp.json()
            shop_data = data['data']
            new_hash = shop_data['hash']
            currentdate = shop_data['date'][:10]

            # Generate custom shop images
            await genshop(session, shop_data, new_hash, custom=True, custom_params=custom_params, saveAs=saveAs, key=key)
            if checkForOgItems:
                await ogitems(session, shop_data, new_hash, custom=True, custom_params=custom_params, saveAs=saveAs, key=key)
            else:
                print("Og items is disabled.")

    # Build the URLs for the generated images
    normal_shop_link = f"/shops/custom/{key}/{saveAs}.jpg"
    og_shop_link = f"/shops/custom/{key}/og-{saveAs}.jpg"

    return {
        "status": "Custom shop images created.",
        "normalShopLink": normal_shop_link,
        "ogShopLink": og_shop_link
    }

@app.get("/api/v1/customShopsAll", include_in_schema=False)
async def get_custom_shops_all(adminKey: str = Depends(check_admin_key)):
    custom_shops = {}
    # Iterate over all keys (directories) in shops/custom/
    key_dirs = [d for d in glob.glob('shops/custom/*') if os.path.isdir(d)]
    for key_dir in key_dirs:
        key = os.path.basename(key_dir)
        custom_shops[key] = []
        for filepath in glob.glob(os.path.join(key_dir, '*.jpg')):
            filename = os.path.basename(filepath)
            custom_shops[key].append(f"/shops/custom/{key}/{filename}")
    return custom_shops

@app.get("/api/v1/customShops/{key}")
async def get_custom_shops_key(key: str):
    key_dir = os.path.join('shops/custom', key)
    if not os.path.exists(key_dir):
        return {"error": "Key not found"}
    custom_shops = []
    for filepath in glob.glob(os.path.join(key_dir, '*.jpg')):
        filename = os.path.basename(filepath)
        custom_shops.append(f"/shops/custom/{key}/{filename}")
    return {"key": key, "customShops": custom_shops}
