"""Stronger hook rules for the first 1-2 seconds (appended to the script prompt)."""
import prompts

HOOK_RULES = (" EK KURALLAR (önceki kurallarla çelişirse BUNLAR geçerlidir; izleyiciler ilk 2 saniyede kaydırıyor): "
              "A) İLK CÜMLE en fazla 5 kelime olsun ve hikayenin EN ŞAŞIRTICI sonucunu veya en çarpıcı somut görüntüsünü "
              "doğrudan söylesin; giriş, bağlam, tarih veya yer anlatımıyla BAŞLAMA. Her seferinde soru sorma; şok edici "
              "bir iddia, yasak, ölüm, kayboluş veya çelişki ile de açabilirsin (örn. Padişah kahveyi idamla cezalandırdı. / "
              "Bu kule bir kez bile düşmedi.). İlk cümlede gerçek bir özel isim ya da gözle görülebilir bir nesne geçsin. "
              "B) İKİNCİ CÜMLE merakı artırsın: 'ama', 'üstelik', 'kimse bilmiyordu ki' gibi bir dönüşle yeni ve somut bir "
              "detay versin; kim, nerede, ne zaman bilgisini en erken ÜÇÜNCÜ sahnede kısaca ver. "
              "C) Her cümle bir sonrakini merak ettirsin; açıklamayı ve cevabı sona sakla, ortada asla tempo düşürme. "
              "D) cover_text de ilk cümlenin en çarpıcı iki kelimesi olsun. "
              "E) Açılışı son video başlıklarındaki kalıplardan farklı kur. "
              "F) Bu kurallar videoyu KISALTMAZ: toplam kelime sayısı BÖLÜM KURALI'ndaki aralıkta kalsın (tek parça videoda "
              "34-42 kelime). Sondan bir önceki sahne gerçek, belgelenmiş ve şaşırtıcı bir TWIST olsun. "
              "G) Günlük konuşma dilinde, sade ve doğru Türkçe yaz; 'gizemle örüldü', 'sırra kadem bastı' gibi süslü, "
              "mecazlı veya anlamı belirsiz ifadeler kullanma; her cümle tek bir somut bilgi versin. "
              "H) Şaşırtıcılık için ASLA doğruluktan ödün verme: ilk cümle dahil her iddia belgelenmiş olsun, abartma ve "
              "olayı başka bir döneme veya kişiye yakıştırma; emin değilsen daha sade ama doğru bir açılış seç.")

if HOOK_RULES not in prompts.SYS:
    prompts.SYS = prompts.SYS + HOOK_RULES
    print("  hook v2 rules active", flush=True)
