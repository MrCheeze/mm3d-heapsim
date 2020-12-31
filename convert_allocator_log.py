import glob

lines = []
addr_to_line = {}
addr_to_file = {}
addr_to_refcounted = {}

#persistent_count = 0
unload_group = -1
lines.append('unload_groups = [{} for i in range(100)]')
for fname in sorted(glob.glob('citra_log_deku_palace_rooms_test_*.txt')):
    temp_count = 0
    lines.append('### %s ###'%fname)
    for line in open(fname):
        line = line.strip().split()
        if line[5] == 'ALLOC':
            lines.append('allocator.alloc(%s, %s)'%(line[6], repr(line[7])))
        elif line[5] == 'ALLOC_RESULT':
            addr_to_refcounted[line[6]] = False
            addr_to_line[line[6]] = len(lines)-1
            addr_to_file[line[6]] = fname
        elif line[5] == 'FREE':
            line_index = addr_to_line[line[6]]
            if addr_to_refcounted[line[6]]:
                pass # refcounted blocks never dealloc
            elif addr_to_file[line[6]] == fname: # loaded earlier during same group
                lines[line_index] = 'temp_%d = %s' % (temp_count, lines[line_index])
                lines.append('allocator.free(temp_%d)'%temp_count)
                temp_count += 1
            else:
                #lines[line_index] = 'persistent_%d = %s # free during %s' % (persistent_count, lines[line_index], fname)
                #lines.append('allocator.free(persistent_%d)'%persistent_count)
                #persistent_count += 1
                if 'for i in sorted(unload_groups' not in lines[-1]:
                    unload_group += 1
                    unload_group_index = 0
                    lines.append('[allocator.free(unload_groups[%d][i]) for i in sorted(unload_groups[%d].keys())]; unload_groups[%d].clear()'%(unload_group,unload_group,unload_group))
                lines[line_index] = 'unload_groups[%d][%d] = %s'%(unload_group, unload_group_index, lines[line_index])
                unload_group_index += 1
                    
        elif line[5] == 'Project':
            pass
        elif line[5] == 'ALLOC_REF':
            lines.append('allocator.allocRefCounted(%s, %s)'%(line[6], line[7]))
        elif line[5] == 'ALLOC_REF_RESULT':
            addr_to_refcounted[line[6]] = True
            addr_to_line[line[6]] = len(lines)-1
            addr_to_file[line[6]] = fname
        elif line[5] == '=================':
            pass
        else:
            print(line)
            1/0


f2 = open('convert_allocator_log_output.txt','w')
for line in lines:
    f2.write(line+'\n')
f2.close()
