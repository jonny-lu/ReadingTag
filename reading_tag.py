# -*- coding: utf-8 -*-

import sublime
import sublime_plugin
import os
import re
import sys
import codecs
import threading
import functools
import linecache

RTAG_PLUGIN_DIR = os.path.basename(os.path.dirname(os.path.realpath(__file__)))
if RTAG_PLUGIN_DIR.find(".sublime-package") != -1:
    RTAG_PLUGIN_DIR = RTAG_PLUGIN_DIR[0:RTAG_PLUGIN_DIR.find(".sublime-package")]

RTAG_SYNTAX_FILE = "Packages/" + RTAG_PLUGIN_DIR + "/Lookup Results.hidden-tmLanguage"

def threaded(finish=None, msg='Thread already running'):
    def decorator(func):
        func.running = 0

        @functools.wraps(func)
        def threaded(*args, **kwargs):
            def run():
                try:
                    result = func(*args, **kwargs)
                    if result is None:
                        result = ()

                    elif not isinstance(result, tuple):
                        result = (result, )

                    if finish:
                        sublime.set_timeout(
                            functools.partial(finish, args[0], *result), 0)
                finally:
                    func.running = 0
            if not func.running:
                func.running = 1
                t = threading.Thread(target=run)
                t.setDaemon(True)
                t.start()
            else:
                sublime.status_message(msg)
        threaded.func = func

        return threaded

    return decorator

class Prefs:
	@staticmethod
	def read():
		pass

	@staticmethod
	def load():
		pass


class TagifyCommon:
    tag_list = {}
    root_dir = None
    ready = False


class ParseTagCommand(sublime_plugin.TextCommand):

	def tagify_file(self, dirname, filename, ctags, folder_prefix):
		filelines = codecs.open(os.path.join(dirname, filename), 'r', 'utf-8')
		# cpos = 0
		try:
			for n, line in enumerate(filelines):
				match = self.tag_re.findall(line)
				for tag in match:
					path = os.path.join(dirname, filename)
					data = {
							'file': path,
							'short_file': "%s:%i" % (path[len(folder_prefix) + 1:], n + 1),
							'line': n + 1
						}
					if tag in ctags:
						ctags[tag].append(data)
					else:
						ctags[tag] = [data]						
		except:
			sublime.status_message('Fail to tagify files')
		finally:
			filelines.close()

	def process_file_list(self, paths, ctags, dir_prefix=None, root_prefix=None):
		for path in paths:
			if dir_prefix:
				dirname = dir_prefix
				filename = path
			else:
				dirname, filename = os.path.split(path)

			if root_prefix:
				folder = root_prefix
			else:
				folder = dirname

			self.tagify_file(dirname, filename, ctags, folder)

	def generate_summary(self, data):
		sorted_tag_list = []
		with codecs.open(os.path.join(self.root_dir, '.tags_detail'), 'w', 'utf-8') as tag_file:
			root_info = "!_ROOT_PREFIX\t%s\n" % self.root_dir
			tag_file.writelines(root_info)
			tag_file.writelines("="*(len(root_info)+10))
			tag_file.writelines('\n')

			line_pos = 2
			for tag in data:
				line_pos += 1
				tag_start = line_pos
				out = []
				out.append("- %s - \n" % tag)
				for entry in data[tag]:
					out.append("%s \n" % entry["short_file"])
					line_pos += 1
				out.append("\n")
				line_pos += 1
				tag_end = line_pos
				tag_file.writelines(out)

				sorted_tag_list.append({'tag':tag, 'start':tag_start, 'end':tag_end})
				TagifyCommon.tag_list[tag] = {'start': tag_start, 'end': tag_end}

		if len(sorted_tag_list) > 0:
			with codecs.open(os.path.join(self.root_dir, '.tags_sorted'), 'w', 'utf-8') as tag_file:
				for tag in sorted_tag_list:
					tag_file.writelines("%s\t%d\t%d\n" % (tag['tag'], tag['start'], tag['end']))

	@threaded(msg='Running ReadingTags!')
	def build_tags(self, paths):
		ctags = {}

		# process current file
		if self.dir_mode:
			for path in paths:
				for dirname, dirnames, filenames in os.walk(path):
					self.process_file_list(filenames, ctags, dirname, path)
		else:
			self.process_file_list(paths, ctags)
		
		unique_ctags = {}
		for tag, regions in ctags.items():
			unique_regions = []
			unique_path_lineno = set()

			for region in regions:
				path_lineno = (region['file'], region['line'])
				if not path_lineno in unique_path_lineno:
					unique_path_lineno.add(path_lineno)
					unique_regions.append(region)
				unique_ctags[tag] = unique_regions

		# generate summary test
		TagifyCommon.ready = True
		TagifyCommon.tag_list = {}
		self.generate_summary(unique_ctags)

	def run(self, edit, **args):
		# self.view.insert(edit, 0, "Hello, World!\n")
		self.tag_re = re.compile(u"#@((?:[\w\u2E80-\u9FFF_a-zA-Z0-9]+))")
		paths = []

		if 'dirs' in args and args['dirs']:
			paths.extend(args['dirs'])
			self.root_dir = args['dirs'][0]
			self.dir_mode = True
		elif 'files' in args and args['files']:
			paths.extend(args['files'])
			self.root_dir, tmp_file = os.path.split(args['files'][0])
			self.dir_mode = False
		else:
			sublime.status_message('Please choose a folder to create tags')
			return

		self.build_tags(paths)

class ShowIndexCommand(sublime_plugin.TextCommand):
    def run(self, edit, data, path):
        out = []
        regions = []
        start_line = data['start']
        end_line = data['end']

        linecache.checkcache(path)
        line = linecache.getline(path, start_line)
        out.append(line)
        cpos = len(line)

        for i in range(start_line+1, end_line):
        	line = linecache.getline(path, i)
        	opos = cpos
        	cpos += len(line)
        	out.append(line)
        	regions.append(sublime.Region(opos, cpos))

        self.view.insert(edit, 0, "".join(out))
        self.view.add_regions("reading-tag-link", regions, "text.tag-index", "",
        	sublime.DRAW_OUTLINED)
        self.view.set_syntax_file(RTAG_SYNTAX_FILE)
        self.view.set_read_only(True)
        self.view.set_scratch(True)


class SearchTagCommand(sublime_plugin.TextCommand):

	def show_tag_panel(self, view, result):
		if result not in (True, False, None):
			args, display = result
			if not args:
				return

			def on_select(i):
				if i != -1:
					# show result
					target = view.window().new_file()
					target.set_name("%s index" % display[i])
					target.run_command("show_index", {"data": args[i], 
													  "path": os.path.join(self.root_dir, '.tags_detail')})


			view.window().show_quick_panel(display, on_select)

	def run(self, edit, **args):
		paths = []
		
		if 'dirs' in args and args['dirs']:
			self.root_dir = args['dirs'][0]
		elif 'files' in args and args['files']:
			self.root_dir, tmp_file = os.path.split(args['files'][0])
		else:
			sublime.status_message('Please choose a folder to search tags')
			return

		args = []
		display = []
		tars_sorted_file = os.path.join(self.root_dir, '.tags_sorted')
		if not os.path.exists(tars_sorted_file):
			sublime.message_dialog('Please choose a folder with tags file')

		TagifyCommon.root_dir = self.root_dir
		if TagifyCommon.ready:
			for tag in TagifyCommon.tag_list.keys():
				args.append({'tag':tag, 
							 'start':TagifyCommon.tag_list[tag]['start'], 
							 'end':TagifyCommon.tag_list[tag]['end']})
				display.append(tag)
		else:
			with codecs.open(os.path.join(tars_sorted_file), 'r', 'utf-8') as tag_file:
				for n, line in enumerate(tag_file):
					try:
						tag, start, end = line.split('\t')
						start = int(start)
						end = int(end)
						args.append({'tag':tag, 'start':start, 'end':end})
						display.append(tag)
						TagifyCommon.tag_list[tag] = {'start': start,
													  'end': end}
						TagifyCommon.ready = True
					except:
						continue

		self.show_tag_panel(self.view, (args, display))


class NavigateToContent(sublime_plugin.TextCommand):

	def __init__(self, *args, **kw):
		super(NavigateToContent, self).__init__(*args, **kw)
		Prefs.load()

	def run(self, edit):
		if not TagifyCommon.root_dir:
			return
		sel = list(self.view.sel())
		if len(sel) != 1:
			return
		sel = sel[0]

		for region in self.view.get_regions('reading-tag-link'):
			if region.contains(sel):
				name = self.view.substr(region)
				short_file, line_no = name.split(':')
				line_no = int(line_no)
				path = os.path.join(TagifyCommon.root_dir, short_file)
				self.view.window().open_file(
					"%s:%i" % (path, line_no), sublime.ENCODED_POSITION)
				self.view.sel().clear()
				return

class AddTagCommand(sublime_plugin.TextCommand):

	def run(self, edit):
		display = []

		if TagifyCommon.ready:
			display.extend(TagifyCommon.tag_list.keys())
		else:
			return

		def on_select(pos):
			if pos == -1:
				pass
			else:
				self.view.run_command('insert', {'characters': '#@'+display[pos]})

		self.view.window().show_quick_panel(display, on_select)