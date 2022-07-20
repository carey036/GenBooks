feed_content = '<div id="{articleid}" class="pagebreak"><h2 class="feedtitle">{title}</h2><p><small>By {author} for <i>{blog}</i>, on {date} at {time}.</small><br></p>{content}</div>'#id从2开始。依次递增；title为feed的title，content为content的内容
feed = '''
<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>{subtitle}</title>
    <style type="text/css">{css}</style>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
  </head>
  <body>
    {feed}
</div>
</div></div></body></html>
'''
css = ".pagebreak{page-break-before:always;}.feedtitle{font-size:1.3em;font-weight:bold;}"
#print(feed.format(**{"subtitle":"哈哈哈","css":css,"feed":"ceui"}))

##上面的用于生成feed

toc = '''
<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>toc</title>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
  </head>
  <body><h2>{subtitle}</h2><ol>     
    {tocbody}
  </ol></body></html>
  '''
toc_content = '<li><a href="feed{feedid}.html#{articleid}">{title}</a></li><br/> '

toc_summary ='''
<?xml version='1.0' encoding='utf-8'?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>Table Of Contents</title>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
  </head>
  <body><h2>Table Of Contents</h2><ul>    
    {toc_summary_body}
  </ul></body></html>
'''
toc_summary_body = '<li><a href="toc_{feedid}.html">{subtitle} ({postnum})</a></li><br/>'

ncx = '''
<?xml version='1.0' encoding='utf-8'?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh-cn">
  <head>
    <meta content="89dd278b-5eb2-4bf9-97ed-ccc788856b7d" name="dtb:uid"/>
    <meta content="4" name="dtb:depth"/>
    <meta content="calibre (1.0.0)" name="dtb:generator"/>
    <meta content="0" name="dtb:totalPageCount"/>
    <meta content="0" name="dtb:maxPageNumber"/>
  </head>
  <docTitle>
    <text>{booktitle}</text>
  </docTitle>
  <navMap>
    <navPoint class="periodical" id="periodical" playOrder="1">
      <navLabel>
        <text>{booktitle}</text>
      </navLabel>
      <content src="toc.html"/>
      {ncx_feed}
    </navPoint>
  </navMap>
</ncx>
'''

ncx_article = '''
<navPoint class="article" id="article-{playorder}" playOrder="{playorder}">
          <navLabel>
            <text>{title}</text>
          </navLabel>
          <content src="feed{feedid}.html#{articleid}"/>
        </navPoint>
'''
##articleNum = playorder + 1 
ncx_feed = '''
<navPoint class="section" id="Main-section-{playorder}" playOrder="{playorder}">
        <navLabel>
          <text>{subtitle} ({postnum})</text>
        </navLabel>
        <content src="feed{feedid}.html"/>
        {ncx_article}
      </navPoint>
'''

opf = '''
<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uuid_id">
  <opf:metadata xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:opf="http://www.idpf.org/2007/opf" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:calibre="http://calibre.kovidgoyal.net/2009/metadata" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:language>zh-cn</dc:language>
    <dc:title>{booktitle} {date}</dc:title>
    <dc:creator>DailyRss</dc:creator>
    <opf:meta name="cover" content="cover"/>
    <dc:date>{date}</dc:date>
    <dc:identifier id="uuid_id" opf:scheme="uuid">89dd278b-5eb2-4bf9-97ed-ccc788856b7d</dc:identifier>
    <opf:meta name="calibre:publication_type" content="periodical:magazine:KindleEar"/>
  </opf:metadata>
  <manifest>
    <item href="cover.jpg" id="cover" media-type="image/jpeg"/>
    {opf_mainfest}
    <item href="toc.html" id="toc" media-type="application/xhtml+xml"/>
    <item href="toc.ncx" media-type="application/x-dtbncx+xml" id="ncx"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="toc"/>
    {opf_ncx}
  </spine>
  <guide>
    <reference href="mh_default.gif" type="other.masthead" title="Masthead Image"/>
    <reference href="cover.jpg" type="cover" title="Cover"/>
    <reference href="toc.html" type="toc" title="Table of Contents"/>
  </guide>
</package>
'''