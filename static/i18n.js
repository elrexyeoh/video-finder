// Interface text in Chinese (default), English and Malay.
window.I18N = (() => {
  const zhTime = s => { const m = Math.floor(s / 60), x = Math.round(s % 60); return (m ? m + '分' : '') + (x ? x + '秒' : ''); };
  const msTime = s => { const m = Math.floor(s / 60), x = Math.round(s % 60); return [m ? m + ' minit' : '', x ? x + ' saat' : ''].filter(Boolean).join(' '); };
  const enTime = s => { const m = Math.floor(s / 60), x = Math.round(s % 60), pl = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`; return [m ? pl(m, 'minute') : '', x ? pl(x, 'second') : ''].filter(Boolean).join(' '); };

  const S = {
    zh: {
      menu: '菜单', nav_ask: 'AI 搜索', nav_ask_long: 'AI 视频搜索', nav_upload: '上传视频', nav_library: '视频库', admin: '管理',
      signout: '退出登录', signed_in_as: '当前用户', new_search: '新的搜索', search: '搜索', cancel: '取消',
      morning: '早上好', afternoon: '下午好', evening: '晚上好',
      stage_title: '需要找什么<em>视频</em>？',
      tap_to_speak: '轻触说话', listening: '正在聆听，请说…', thinking: '正在 {n} 个视频中查找…', empty_short: '视频库还是空的',
      try_saying: '试试说：“{ex}”',
      examples: ['找有蓝色花纹沙发床的视频', '仓库里堆放的钢管', '工厂的航拍画面', '有人在台上演讲'],
      type_ph: '或输入想找的画面…',
      found: '找到 <b>{n} 个视频</b>，画面中有<em>{what}</em>。',
      best: '最佳匹配是 <b>{file}</b>，{when}。', at_start: '就在开头', at_time: '在 {t}',
      close_only: '没有完全符合的，但这几个最接近。',
      none: '在视频库的 {n} 个视频中，没有找到<em>{what}</em>。',
      none_tip: '可以换个说法试试，例如描述颜色、场景或正在发生的事情。',
      pending: '另有 {n} 个视频仍在处理中，暂时无法搜索。',
      empty: '视频库还是空的。请先上传视频，之后我就能帮您查找。',
      error: '搜索时出错了，请再试一次。',
      strong: '高度匹配', possible: '可能匹配', moments: '匹配片段', download: '下载',
      say_empty: '视频库还是空的，请先上传视频。', say_none: '抱歉，没有找到{what}的画面。', say_found: '我找到了{n}个视频。',
      say_best: p => `最佳匹配在${p.s < 2 ? '视频开头' : zhTime(p.s)}。`,
      voice_unsupported: '此浏览器不支持语音搜索，请使用 Chrome、Edge 或 Safari，或直接输入文字。',
      mic_blocked: '麦克风权限被阻止，请在浏览器设置中允许使用麦克风。', no_speech: '没有听到声音，请再轻触麦克风试试。',
      voice_err: '语音识别中断（{e}），请重试。', mic_fail: '无法启动麦克风，请重试。',
      up_eyebrow: '添加到视频库', up_title: '上传<em>视频</em>', up_desc: '支持任何格式：MP4、MOV、iPhone 视频、AVI、MKV 等。上传后约一两分钟即可搜索。',
      up_choose: '选择要上传的视频', up_drag: '或拖放到这里 · 可一次选择多个', waiting: '等待中', uploaded: '已上传 · 处理中', failed: '上传失败', net_err: '网络错误',
      lib_eyebrow: '全部已上传的视频', lib_title: '视频<em>库</em>', filter: '按文件名筛选',
      st_videos: '视频', st_searchable: '可搜索', st_footage: '总时长', st_stored: '已用空间',
      s_ready: '可搜索', s_error: '出错', s_conv: '转换中…', s_idx: '分析中 {p}%', s_queue: '排队中',
      delete: '删除', confirm_del: '确定要为所有人删除“{f}”吗？', still_proc: '该视频仍在处理中。',
      no_match_name: '没有符合该名称的视频。', no_videos: '还没有视频，请先上传。', cant_delete: '无法删除',
      login_eyebrow: 'AI 视频助理', login_title: '智能视频<em>搜索</em>', login_sub: '说出画面内容，即刻找到视频。',
      name: '您的名字', name_ph: '例如：Alex', pw: '团队密码', signin: '登录', signing_in: '正在登录…', wrong_pw: '密码错误，请重试。',
      foot: 'TSLAW Group · 内部使用',
    },
    en: {
      menu: 'Menu', nav_ask: 'Ask AI', nav_ask_long: 'AI video search', nav_upload: 'Upload videos', nav_library: 'Library', admin: 'Admin',
      signout: 'Sign out', signed_in_as: 'Signed in as', new_search: 'New search', search: 'Search', cancel: 'Cancel',
      morning: 'Good morning', afternoon: 'Good afternoon', evening: 'Good evening',
      stage_title: 'Which <em>video</em> do you need?',
      tap_to_speak: 'Tap to speak', listening: 'Listening… go ahead', thinking: 'Searching {n} videos…', empty_short: 'The library is empty',
      try_saying: 'Try saying: “{ex}”',
      examples: ['Find videos with a blue floral sofa bed', 'Steel pipes stacked in a warehouse', 'Aerial view of a factory', 'Someone presenting on stage'],
      type_ph: 'Or type what you’re looking for…',
      found: p => `I found <b>${p.n} video${p.n === 1 ? '' : 's'}</b> showing <em>${p.what}</em>.`,
      best: 'The best match is <b>{file}</b>, {when}.', at_start: 'right at the start', at_time: 'at {t}',
      close_only: 'None is a perfect match, but these look closest.',
      none: 'I couldn’t find any video showing <em>{what}</em> among the {n} videos in the library.',
      none_tip: 'Try describing it another way, for example the colours, the setting or what is happening.',
      pending: p => `${p.n} video${p.n === 1 ? ' is' : 's are'} still being processed and can’t be searched yet.`,
      empty: 'The library is empty, so there’s nothing to search yet. Upload some videos and I’ll find them for you.',
      error: 'Sorry, something went wrong while searching. Please try again.',
      strong: 'Strong match', possible: 'Possible match', moments: 'Matching moments', download: 'Download',
      say_empty: 'The library is empty. Please upload some videos first.', say_none: 'Sorry, I couldn’t find any video showing {what}.',
      say_found: p => `I found ${p.n} video${p.n === 1 ? '' : 's'}.`,
      say_best: p => `The best match is ${p.s < 2 ? 'right at the start' : enTime(p.s) + ' in'}.`,
      voice_unsupported: 'Voice search isn’t supported in this browser. Please use Chrome, Edge or Safari, or type instead.',
      mic_blocked: 'Microphone access is blocked. Allow it in your browser settings to use voice search.', no_speech: 'I didn’t hear anything. Tap the mic and try again.',
      voice_err: 'Voice search stopped ({e}). Please try again.', mic_fail: 'Could not start the microphone. Please try again.',
      up_eyebrow: 'Add to the library', up_title: 'Upload <em>videos</em>', up_desc: 'Any format works: MP4, MOV, iPhone videos, AVI, MKV and more. Each video becomes searchable a minute or two after it uploads.',
      up_choose: 'Choose videos to upload', up_drag: 'or drag and drop them here · select as many as you like', waiting: 'waiting', uploaded: 'Uploaded · processing', failed: 'Failed', net_err: 'Network error',
      lib_eyebrow: 'Everything uploaded', lib_title: 'Video <em>library</em>', filter: 'Filter by file name',
      st_videos: 'Videos', st_searchable: 'Searchable', st_footage: 'Footage', st_stored: 'Stored',
      s_ready: 'Searchable', s_error: 'Error', s_conv: 'Converting…', s_idx: 'Analysing {p}%', s_queue: 'In queue',
      delete: 'Delete', confirm_del: 'Delete “{f}” for everyone?', still_proc: 'This video is still being processed.',
      no_match_name: 'No videos match that name.', no_videos: 'No videos yet. Upload some to get started.', cant_delete: 'Could not delete',
      login_eyebrow: 'AI video assistant', login_title: 'Video <em>Finder</em>', login_sub: 'Describe a scene, and I’ll find the video.',
      name: 'Your name', name_ph: 'e.g. Alex', pw: 'Team password', signin: 'Sign in', signing_in: 'Signing in…', wrong_pw: 'Wrong password. Please try again.',
      foot: 'TSLAW Group · Internal use',
    },
    ms: {
      menu: 'Menu', nav_ask: 'Tanya AI', nav_ask_long: 'Carian video AI', nav_upload: 'Muat naik video', nav_library: 'Pustaka video', admin: 'Pentadbir',
      signout: 'Log keluar', signed_in_as: 'Log masuk sebagai', new_search: 'Carian baharu', search: 'Cari', cancel: 'Batal',
      morning: 'Selamat pagi', afternoon: 'Selamat petang', evening: 'Selamat malam',
      stage_title: '<em>Video</em> apa yang anda perlukan?',
      tap_to_speak: 'Ketik untuk bercakap', listening: 'Sedang mendengar… sila cakap', thinking: 'Mencari dalam {n} video…', empty_short: 'Pustaka masih kosong',
      try_saying: 'Cuba sebut: “{ex}”',
      examples: ['Cari video sofa katil biru bercorak bunga', 'Paip keluli bertimbun di gudang', 'Pemandangan udara kilang', 'Orang membentang di pentas'],
      type_ph: 'Atau taip apa yang anda cari…',
      found: 'Saya jumpa <b>{n} video</b> yang menunjukkan <em>{what}</em>.',
      best: 'Padanan terbaik ialah <b>{file}</b>, {when}.', at_start: 'di permulaan', at_time: 'pada {t}',
      close_only: 'Tiada yang betul-betul sepadan, tetapi ini yang paling hampir.',
      none: 'Saya tidak jumpa video yang menunjukkan <em>{what}</em> dalam {n} video di pustaka.',
      none_tip: 'Cuba terangkan dengan cara lain, contohnya warna, lokasi atau apa yang berlaku.',
      pending: '{n} video masih diproses dan belum boleh dicari.',
      empty: 'Pustaka video masih kosong. Muat naik video dahulu dan saya akan carikan untuk anda.',
      error: 'Maaf, berlaku ralat semasa mencari. Sila cuba lagi.',
      strong: 'Padanan kuat', possible: 'Mungkin sepadan', moments: 'Detik sepadan', download: 'Muat turun',
      say_empty: 'Pustaka video masih kosong. Sila muat naik video dahulu.', say_none: 'Maaf, saya tidak jumpa video yang menunjukkan {what}.', say_found: 'Saya jumpa {n} video.',
      say_best: p => `Padanan terbaik ${p.s < 2 ? 'ada di permulaan video' : 'pada ' + msTime(p.s)}.`,
      voice_unsupported: 'Carian suara tidak disokong dalam pelayar ini. Sila guna Chrome, Edge atau Safari, atau taip sahaja.',
      mic_blocked: 'Akses mikrofon disekat. Benarkan dalam tetapan pelayar untuk guna carian suara.', no_speech: 'Saya tidak dengar apa-apa. Ketik mikrofon dan cuba lagi.',
      voice_err: 'Carian suara terhenti ({e}). Sila cuba lagi.', mic_fail: 'Mikrofon tidak dapat dimulakan. Sila cuba lagi.',
      up_eyebrow: 'Tambah ke pustaka', up_title: 'Muat naik <em>video</em>', up_desc: 'Semua format diterima: MP4, MOV, video iPhone, AVI, MKV dan lain-lain. Video boleh dicari kira-kira seminit dua selepas dimuat naik.',
      up_choose: 'Pilih video untuk dimuat naik', up_drag: 'atau seret ke sini · boleh pilih banyak sekali gus', waiting: 'menunggu', uploaded: 'Dimuat naik · sedang diproses', failed: 'Gagal', net_err: 'Ralat rangkaian',
      lib_eyebrow: 'Semua yang dimuat naik', lib_title: 'Pustaka <em>video</em>', filter: 'Tapis ikut nama fail',
      st_videos: 'Video', st_searchable: 'Boleh dicari', st_footage: 'Jumlah masa', st_stored: 'Storan',
      s_ready: 'Boleh dicari', s_error: 'Ralat', s_conv: 'Menukar format…', s_idx: 'Menganalisis {p}%', s_queue: 'Dalam giliran',
      delete: 'Padam', confirm_del: 'Padam “{f}” untuk semua orang?', still_proc: 'Video ini masih diproses.',
      no_match_name: 'Tiada video dengan nama itu.', no_videos: 'Belum ada video. Muat naik dahulu.', cant_delete: 'Tidak dapat dipadam',
      login_eyebrow: 'Pembantu video AI', login_title: 'Pencari <em>Video</em>', login_sub: 'Terangkan babak, saya akan cari videonya.',
      name: 'Nama anda', name_ph: 'cth. Alex', pw: 'Kata laluan pasukan', signin: 'Log masuk', signing_in: 'Sedang log masuk…', wrong_pw: 'Kata laluan salah. Sila cuba lagi.',
      foot: 'TSLAW Group · Kegunaan dalaman',
    },
  };
  const VOICE = { zh: 'zh-CN', en: 'en-US', ms: 'ms-MY' };
  const LOCALE = { zh: 'zh-CN', en: 'en-GB', ms: 'ms-MY' };
  const LABEL = { zh: '中文', en: 'EN', ms: 'BM' };
  let lang = 'zh';  // Chinese is the default
  try { const saved = localStorage.getItem('uiLang'); if (S[saved]) lang = saved; } catch {}

  function t(key, p = {}) {
    let s = S[lang][key];
    if (s === undefined) s = S.en[key];
    if (s === undefined) return key;
    if (typeof s === 'function') return s(p);
    if (typeof s !== 'string') return s;
    return s.replace(/\{(\w+)\}/g, (m, k) => (p[k] !== undefined ? p[k] : m));
  }
  function apply(root = document) {
    document.documentElement.lang = LOCALE[lang];
    root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-html]').forEach(el => { el.innerHTML = t(el.dataset.i18nHtml); });
    root.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
    root.querySelectorAll('[data-i18n-aria]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); el.setAttribute('aria-label', el.title); });
  }
  function mountSwitch(el, onChange) {
    const render = () => {
      el.innerHTML = Object.keys(S).map(k => `<button type="button" data-lang="${k}" aria-pressed="${k === lang}" lang="${LOCALE[k]}">${LABEL[k]}</button>`).join('');
      el.querySelectorAll('button').forEach(b => b.onclick = () => {
        lang = b.dataset.lang;
        try { localStorage.setItem('uiLang', lang); } catch {}
        render(); apply(document); onChange && onChange(lang);
      });
    };
    render();
  }
  return { t, apply, mountSwitch, get lang() { return lang; }, voiceCode: l => VOICE[l || lang], locale: () => LOCALE[lang] };
})();
