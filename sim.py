# ported from Leoetlino's original MM3D heapsim code

import math
from sim_actions import *
import random

Flag_IsRefCounted = 1 << 0
Flag_PreventReuse = 1 << 1
Flag_FreeBlockOnRefCountZero = 1 << 3

class Allocator:
    def __init__(self):

        self.dummy_block = AllocatorBlock(0xDEADBEEF)
        self.dummy_block.next_free_l = 0x8010000
        self.dummy_block.next_free_s = 0x8010000
        self.dummy_block.refcounted_next = self.dummy_block.addr
        self.dummy_block.refcounted_prev = self.dummy_block.addr

        initial_block = AllocatorBlock(0x8010000)
        initial_block.size = 0x1897000
        initial_block.next_free_l = 0xDEADBEEF
        initial_block.next_free_s = 0xDEADBEEF
        initial_block.prev = 0x8010000
        initial_block.next = 0x8010000
        
        self.ram = {0xDEADBEEF: self.dummy_block, 0x8010000: initial_block}

        self.load_planes = {'right_upper':0,
                            'left_upper':0,
                            'right_lower':0,
                            'left_lower':0,
                            'right_backdoor':0}

    def alloc(self, size, name):
        ptr = 0;
        while True:
            ptr = self.allocSmall(size) if 0x800 > size else self.allocLarge(size)
            if ptr:
                break
            if self.freeUnusedRefCountedBlock(size):
                return ptr;

        block = self.ram[ptr]
        block.next_free_s = 0
        block.next_free_l = 0
        block.name = name
        block.magic = 0x12345678ABCDEF86
        block.alloc_ticks = -1

        return ptr+0x40

    def allocLarge(self, size):
        block = self.ram[self.dummy_block.next_free_l]
        alloc_size = math.ceil(size / 0x10) * 0x10 + 0x40
        while True:
            if block.size - alloc_size >= 0:
                break

            block = self.ram[block.next_free_l]
            if block.addr == self.dummy_block.addr:
                return 0
            
        new_free_size = block.size - alloc_size
        if block.size == alloc_size or new_free_size <= 0x40:
            self.ram[block.next_free_s].next_free_l = block.next_free_l
            self.ram[block.next_free_l].next_free_s = block.next_free_s
            block.id = 0
            block.flags = 0
            block.ref_count = 1
            block.size = -block.size
            return block.addr

        new_block = AllocatorBlock(block.addr + alloc_size)
        self.ram[new_block.addr] = new_block
        self.ram[block.next_free_s].next_free_l = block.next_free_l
        self.ram[block.next_free_l].next_free_s = block.next_free_s
        block.id = 0
        block.flags = 0
        block.ref_count = 1
        block.size = -alloc_size

        new_block.id = 0
        new_block.flags = 0
        new_block.ref_count = 1
        new_block.prev = block.addr
        new_block.size = new_free_size
        
        self.ram[block.next].prev = new_block.addr
        new_block.next = block.next
        block.next = new_block.addr

        self.updateFreeLists(new_block)

        return block.addr

    def updateFreeLists(self, block):
        free_block = self.ram[block.prev]
        while free_block.size <= 0:
            free_block = self.ram[free_block.prev]
        if free_block.addr == block.addr:
            self.ram[self.dummy_block.next_free_s].next_free_l = block.addr
            block.next_free_l = self.dummy_block.addr
            block.next_free_s = self.dummy_block.next_free_s
            self.dummy_block.next_free_s = block.addr
        else:
            self.ram[free_block.next_free_l].next_free_s = block.addr
            block.next_free_s = free_block.addr
            block.next_free_l = free_block.next_free_l
            free_block.next_free_l = block.addr


    def allocSmall(self, size):
        block = self.ram[self.dummy_block.next_free_s]
        alloc_size = math.ceil(size / 0x10) * 0x10 + 0x40
        while True:
            if block.size - alloc_size >= 0:
                break

            block = self.ram[block.next_free_s]
            if block.addr == self.dummy_block.addr:
                return 0
            
        new_free_size = block.size - alloc_size
        if block.size == alloc_size or new_free_size <= 0x40:
            self.ram[block.next_free_s].next_free_l = block.next_free_l
            self.ram[block.next_free_l].next_free_s = block.next_free_s
            block.id = 0
            block.flags = 0
            block.ref_count = 1
            block.size = -block.size
            return block.addr

        new_block = AllocatorBlock(block.addr + new_free_size)
        self.ram[new_block.addr] = new_block

        new_block.id = 0
        new_block.flags = 0
        new_block.ref_count = 1
        new_block.prev = block.addr
        new_block.size = -alloc_size
        block.size = new_free_size
        
        self.ram[block.next].prev = new_block.addr
        new_block.next = block.next
        block.next = new_block.addr

        return new_block.addr

    def free(self, ptr):
        if not ptr:
            return

        block = self.ram[ptr-0x40]

        if block.flags & Flag_IsRefCounted:
            if block.ref_count != 0:
                block.ref_count -= 1

                if (block.ref_count == 0 and
                    block.flags & Flag_FreeBlockOnRefCountZero):
                    self.ram[block.refcounted_next].refcounted_prev = block.refcounted_prev
                    self.ram[block.refcounted_prev].refcounted_next = block.refcounted_next
                    block.refcounted_next = 0
                    block.refcounted_prev = 0
                    self.doFree(ptr)
                
        else:
            self.doFree(ptr)

    def doFree(self, ptr):
        block = self.ram[ptr-0x40]

        block.name = ''
        block.size = -block.size
        self.updateFreeLists(block)
        self.tryToMergeBlock(block)

    def tryToMergeBlock(self, block):
        def merge_into(target, other):
            target.size += other.size
            self.ram[other.next_free_s].next_free_l = other.next_free_l
            self.ram[other.next_free_l].next_free_s = other.next_free_s

            self.ram[other.prev].next = other.next
            self.ram[other.next].prev = other.prev

            del self.ram[other.addr]

        next_block = self.ram[block.next]
        if next_block.size > 0 and block.addr + block.size == next_block.addr:
            merge_into(block, next_block)

        prev_block = self.ram[block.prev]
        if prev_block.size > 0 and block.addr - prev_block.size == prev_block.addr:
            merge_into(prev_block, block)

        return block

    def allocRefCounted(self, alloc_id, size):
        ptr = 0
        while True:
            ptr = self.allocLarge(size)
            if ptr:
                break
            if not self.freeUnusedRefCountedBlock(size):
                return ptr

        block = self.ram[ptr]
        block.id = alloc_id
        block.flags = Flag_IsRefCounted
        block.name = '(reference counted)'
        block.alloc_ticks = -1

        self.ram[self.dummy_block.refcounted_next].refcounted_prev = block.addr
        block.refcounted_next = self.dummy_block.refcounted_next
        block.refcounted_prev = self.dummy_block.addr
        self.dummy_block.refcounted_next = block.addr

        return ptr + 0x40

    def validate_integrity(self):
        total_size = 0
        for addr in self.ram:

            if addr == self.dummy_block.addr:
                continue
            
            node = self.ram[addr]
            total_size += abs(node.size)
            assert self.ram[node.next].prev==node.addr
            assert self.ram[node.prev].next==node.addr

        assert total_size == 0x1897000
    
    def __repr__(self):
        return '\n'.join(repr(self.ram[addr]) for addr in sorted(self.ram) if addr != self.dummy_block.addr)

class AllocatorBlock:
    def __init__(self, addr):
        self.addr = addr
        self.name = ''
        self.size = 0

    def __repr__(self):
        if self.size > 0: # FREE
            return '%08x FREE (free) size=%x' % (self.addr, self.size)
        elif self.flags & Flag_IsRefCounted: #refcounted
            return '%08x USED (reference counted) size=%x ref_count=%d' % (self.addr, -self.size, self.ref_count)
        else: #normal
            return '%08x USED %s size=%x' % (self.addr, self.name, -self.size)
    

'''
prev_time = 5

allocator_traces = [
    'citra_log_deku_palace_rooms_test_01_bootup.txt',
    'citra_log_deku_palace_rooms_test_02_fileselect.txt',
    'citra_log_deku_palace_rooms_test_03_palace_scene_load.txt',
    'citra_log_deku_palace_rooms_test_04_turn_away_from_statue.txt',
    'citra_log_deku_palace_rooms_test_05_look_towards_palace.txt',
    'citra_log_deku_palace_rooms_test_06_triple_slash_clip.txt',
    'citra_log_deku_palace_rooms_test_07_left_room.txt',
    'citra_log_deku_palace_rooms_test_08_center_room.txt',
    'citra_log_deku_palace_rooms_test_09_left_room.txt',
    'citra_log_deku_palace_rooms_test_10_center_room.txt',
    'citra_log_deku_palace_rooms_test_11_right_room.txt',
    'citra_log_deku_palace_rooms_test_12_center_room.txt',
    'citra_log_deku_palace_rooms_test_13_right_room.txt',
    'citra_log_deku_palace_rooms_test_14_center_room.txt',
    'citra_log_deku_palace_rooms_test_15_take_out_bomb.txt',
    'citra_log_deku_palace_rooms_test_16_bomb_explodes.txt',
    'citra_log_deku_palace_rooms_test_17_smoke_dissipates.txt',
]

for fname in allocator_traces:

    for line in open(fname):
        
        line_split = line.split()

        if ' ALLOC ' in line:
            alloc_size = int(line_split[-2], base=16)
            alloc_name = line_split[-1]
            last_returned_addr = allocator.alloc(alloc_size, alloc_name)
        elif ' ALLOC_RESULT ' in line:
            expected_addr = int(line_split[-3], base=16) - 0x40
            expected_size = int(line_split[-2], base=16)
            expected_name = line_split[-1]
            assert last_returned_addr-0x40 == expected_addr
            assert expected_addr in allocator.ram
            assert allocator.ram[expected_addr].size == -expected_size
            assert allocator.ram[expected_addr].name == expected_name
        elif ' FREE ' in line:
            free_addr = int(line_split[-1], base=16)
            allocator.free(free_addr)
        elif 'Project Restoration initialised' in line:
            pass
        elif ' ALLOC_REF ' in line:
            alloc_id = int(line_split[-1], base=16)
            alloc_size = int(line_split[-1], base=16)
            last_returned_addr = allocator.allocRefCounted(alloc_id, alloc_size)
        elif ' ALLOC_REF_RESULT ' in line:
            expected_addr = int(line_split[-3], base=16) - 0x40
            expected_size = int(line_split[-2], base=16)
            expected_unk = int(line_split[-1])
            assert last_returned_addr-0x40 == expected_addr
            assert expected_addr in allocator.ram
            assert allocator.ram[expected_addr].size == -expected_size
            assert allocator.ram[expected_addr].name == '(reference counted)'
            assert allocator.ram[expected_addr].ref_count == expected_unk
            assert allocator.ram[expected_addr].flags == expected_unk
        elif 'statue changed' in line:
            expected_statue_addr = int(line_split[-1], base=16) - 0x40
            if expected_statue_addr > 0:
                assert allocator.ram[expected_statue_addr].size == -0x2d0
                assert allocator.ram[expected_statue_addr].name == 'C:\\Jenkins\\workspace\\joker\\prog\\game\\sources\\original\\z_actor.cpp(10836)'
        else:
            print(line_split)
            1/0

        time = float(line_split[1][:-1])
        time_delta = time-prev_time
        if time_delta > 1:
            pass#print(time_delta, prev_time, time)
        prev_time = time

"""def center_to_left(firstLoad=False):
    pass

def left_to_center():
    pass

def center_to_right(firstLoad=False):
    pass

def right_to_center():
    pass

center_to_left(firstLoad=True)
left_to_center()
center_to_left()
left_to_center()

center_to_right(firstLoad=True)
right_to_center()
center_to_right()
right_to_center()"""

print(allocator)
'''

'''
count=0
for line in open('convert_allocator_log_output.txt'):
    #if 'citra_log_deku_palace_rooms_test_03_palace_scene_load' in line:
    #    print(''+line.strip())
    #    break
    
    exec(line)
print(allocator)
#'''


'''for action1 in range(3):
 for action2 in range(3):
  for action3 in range(3):
   for action4 in range(3):
    for action5 in range(3):
     for action6 in range(3):
      for action7 in range(3):
       for action8 in range(3):
        print(action1,action2,action3,action4,action5,action6,action7,action8)
        for first_bomb_time in range(10):
         for sparks_before_dust in [True,False]:'''


for action1,action2,action3,action4,action5,action6,action7,action8,first_bomb_time,sparks_before_dust in [
    [0, 0, 0, 1, 0, 2, 1, 2,  8, True],
    [0, 0, 2, 1, 0, 0, 0, 2,  0, True],
    [0, 1, 2, 1, 2, 2, 2, 2,  8, False],
    [1, 1, 2, 2, 1, 1, 1, 2,  9, False],
    [2, 1, 2, 2, 2, 1, 1, 2,  4, True],
    [2, 2, 1, 1, 0, 0, 2, 2,  3, False],
    [2, 2, 1, 2, 1, 1, 1, 2,  7, True],
    [2, 2, 2, 2, 1, 2, 1, 2,  7, True]
    ]:

            allocator = Allocator()
            initial_load(allocator)

            if first_bomb_time == 0:
                explode_bomb(allocator, sparks_before_dust)

            if action1 == 1:
                center_to_left(allocator, top_door=False)
                if first_bomb_time == 1:
                    explode_bomb(allocator, sparks_before_dust)
                left_to_center(allocator, top_door=False)
            elif action1 == 2:
                center_to_right(allocator, top_door=False)
                if first_bomb_time == 1:
                    explode_bomb(allocator, sparks_before_dust)
                right_to_center(allocator, top_door=False)

            if first_bomb_time == 2:
                explode_bomb(allocator, sparks_before_dust)
                
            if action2 == 1:
                center_to_left(allocator, top_door=False)
                if first_bomb_time == 3:
                    explode_bomb(allocator, sparks_before_dust)
                left_to_center(allocator, top_door=False)
            elif action2 == 2:
                center_to_right(allocator, top_door=False)
                if first_bomb_time == 3:
                    explode_bomb(allocator, sparks_before_dust)
                right_to_center(allocator, top_door=False)

            if first_bomb_time == 4:
                explode_bomb(allocator, sparks_before_dust)
                
            if action3 == 1:
                center_to_left(allocator, top_door=False)
                if first_bomb_time == 5:
                    explode_bomb(allocator, sparks_before_dust)
                left_to_center(allocator, top_door=False)
            elif action3 == 2:
                center_to_right(allocator, top_door=False)
                if first_bomb_time == 5:
                    explode_bomb(allocator, sparks_before_dust)
                right_to_center(allocator, top_door=False)

            if first_bomb_time == 6:
                explode_bomb(allocator, sparks_before_dust)
                
            if action4 == 1:
                center_to_left(allocator, top_door=False)
                if first_bomb_time == 7:
                    explode_bomb(allocator, sparks_before_dust)
                left_to_center(allocator, top_door=False)
            elif action4 == 2:
                center_to_right(allocator, top_door=False)
                if first_bomb_time == 7:
                    explode_bomb(allocator, sparks_before_dust)
                right_to_center(allocator, top_door=False)

            if first_bomb_time == 8:
                explode_bomb(allocator, sparks_before_dust)
            
            center_to_left(allocator, top_door=False)
            explode_bomb(allocator, sparks_before_dust)
            shoot_nut(allocator)
            left_to_center(allocator, top_door=True)
                
            if action5 == 1:
                center_to_left(allocator, top_door=True)
                left_to_center(allocator, top_door=True)
            elif action5 == 2:
                center_to_right(allocator, top_door=True)
                right_to_center(allocator, top_door=True)
                
            if action6 == 1:
                center_to_left(allocator, top_door=True)
                left_to_center(allocator, top_door=True)
            elif action6 == 2:
                center_to_right(allocator, top_door=True)
                right_to_center(allocator, top_door=True)

            if action7 == 1:
                center_to_left(allocator, top_door=True)
                left_to_center(allocator, top_door=True)
            elif action7 == 2:
                center_to_right(allocator, top_door=True)
                right_to_center(allocator, top_door=True)

            if action8 == 1:
                center_to_left(allocator, top_door=True)
                left_to_center(allocator, top_door=True)
            elif action8 == 2:
                center_to_right(allocator, top_door=True)
                right_to_center(allocator, top_door=True)
                
            center_to_right(allocator, top_door=True)

            despawn = 0x3FFF
            #despawn = random.randint(0,0xFFFF) | random.randint(0,0xFFFF) | random.randint(0,0xFFFF)

            # other pot
            if despawn & 1:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][28]); del allocator.unload_groups[LEAVING_RIGHT_1][28]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][17]); del allocator.unload_groups[LEAVING_RIGHT_2][17]

            for addr in allocator.ram:
                if abs(allocator.ram[addr].size) == 0x2E0 and 'Obj_Tsubo' in allocator.ram[addr].name:
                    print(str(allocator.ram[addr]), action1, action2, action3, action4, action5, action6, action7, action8, '-', first_bomb_time, sparks_before_dust)
                    #print(allocator)
                    tsubo_addr = addr
                    break
            else:
                continue

            night_transition(allocator)

            # SRM pot
            allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][29]); del allocator.unload_groups[LEAVING_RIGHT_1][29]
            allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][18]); del allocator.unload_groups[LEAVING_RIGHT_2][18]

            # scattered rupees
            if despawn & 2:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][34]); del allocator.unload_groups[LEAVING_RIGHT_1][34]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][21]); del allocator.unload_groups[LEAVING_RIGHT_2][21]
            if despawn & 4:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][35]); del allocator.unload_groups[LEAVING_RIGHT_1][35]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][22]); del allocator.unload_groups[LEAVING_RIGHT_2][22]
            if despawn & 8:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][36]); del allocator.unload_groups[LEAVING_RIGHT_1][36]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][23]); del allocator.unload_groups[LEAVING_RIGHT_2][23]
            if despawn & 0x10:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][37]); del allocator.unload_groups[LEAVING_RIGHT_1][37]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][24]); del allocator.unload_groups[LEAVING_RIGHT_2][24]
            if despawn & 0x20:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][38]); del allocator.unload_groups[LEAVING_RIGHT_1][38]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][25]); del allocator.unload_groups[LEAVING_RIGHT_2][25]
            if despawn & 0x40:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][39]); del allocator.unload_groups[LEAVING_RIGHT_1][39]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][26]); del allocator.unload_groups[LEAVING_RIGHT_2][26]
            #if despawn & 0x80:
            #    allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][40]); del allocator.unload_groups[LEAVING_RIGHT_1][40]
            #    allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][27]); del allocator.unload_groups[LEAVING_RIGHT_2][27]
            #if despawn & 0x100:
            #    allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][41]); del allocator.unload_groups[LEAVING_RIGHT_1][41]
            #    allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][28]); del allocator.unload_groups[LEAVING_RIGHT_2][28]
            if despawn & 0x80:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][42]); del allocator.unload_groups[LEAVING_RIGHT_1][42]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][29]); del allocator.unload_groups[LEAVING_RIGHT_2][29]
            if despawn & 0x100:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][43]); del allocator.unload_groups[LEAVING_RIGHT_1][43]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][30]); del allocator.unload_groups[LEAVING_RIGHT_2][30]
            if despawn & 0x200:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][44]); del allocator.unload_groups[LEAVING_RIGHT_1][44]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][31]); del allocator.unload_groups[LEAVING_RIGHT_2][31]
            if despawn & 0x400:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][45]); del allocator.unload_groups[LEAVING_RIGHT_1][45]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][32]); del allocator.unload_groups[LEAVING_RIGHT_2][32]
            if despawn & 0x800:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][46]); del allocator.unload_groups[LEAVING_RIGHT_1][46]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][33]); del allocator.unload_groups[LEAVING_RIGHT_2][33]
            if despawn & 0x1000:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][47]); del allocator.unload_groups[LEAVING_RIGHT_1][47]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][34]); del allocator.unload_groups[LEAVING_RIGHT_2][34]
            if despawn & 0x2000:
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_1][48]); del allocator.unload_groups[LEAVING_RIGHT_1][48]
                allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][35]); del allocator.unload_groups[LEAVING_RIGHT_2][35]
            
            right_to_center(allocator, top_door=False)

            for addr in allocator.ram:
                if allocator.ram[addr].name == 'Obj_Warpstone':
                    print(str(allocator.ram[addr]), hex(despawn), tsubo_addr-addr)
                    
            """center_to_right(allocator, top_door=False)
            right_to_center(allocator, top_door=False)

            for addr in allocator.ram:
                if allocator.ram[addr].name == 'Obj_Warpstone':
                    print(str(allocator.ram[addr]))
                    
            center_to_right(allocator, top_door=False)
            right_to_center(allocator, top_door=False)

            for addr in allocator.ram:
                if allocator.ram[addr].name == 'Obj_Warpstone':
                    print(str(allocator.ram[addr]))"""

'''allocator = Allocator()
initial_load(allocator)
explode_bomb(allocator, False)
center_to_right(allocator, top_door=False)
right_to_center(allocator, top_door=False)
center_to_left(allocator, top_door=False)
left_to_center(allocator, top_door=False)
center_to_left(allocator, top_door=False)
explode_bomb(allocator, False)
shoot_nut(allocator)
left_to_center(allocator, top_door=True)
center_to_right(allocator, top_door=True)
right_to_center(allocator, top_door=True)
center_to_right(allocator, top_door=True)
for addr in allocator.ram:
    if allocator.ram[addr].name == 'Obj_Tsubo' and abs(allocator.ram[addr].size) == 0x2E0:
        print(str(allocator.ram[addr]))

print(allocator)

#night_transition(allocator)

#allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][18])
#del allocator.unload_groups[LEAVING_RIGHT_2][18]
#allocator.free(allocator.unload_groups[LEAVING_RIGHT_2][29])
#del allocator.unload_groups[LEAVING_RIGHT_2][29]

#right_to_center(allocator, top_door=False)
#for addr in allocator.ram:
#    if allocator.ram[addr].name == 'Obj_Warpstone':
#        print(str(allocator.ram[addr]))
#print(allocator)
'''
